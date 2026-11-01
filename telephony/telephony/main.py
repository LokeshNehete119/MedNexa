"""FastAPI application for the telephony server.

Starts a small HTTP + WebSocket server that:
  - Receives Twilio webhooks (POST /twilio/voice)
  - Handles Twilio Media Streams (WS /twilio/stream/{call_sid})
  - Exposes a health check (GET /health)
  - Exposes a WebSocket bridge for local testing (WS /ws/call)

Run with::

    uvicorn telephony.main:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from telephony.api_client import BackendClient
from telephony.config import get_settings
from telephony.logging_setup import configure_logging, get_logger
from telephony.stt import FasterWhisperSTT
from telephony.twilio_handler import router as twilio_router
from telephony.vad import SileroVAD

# Configure logging at import time so structlog uses its stdlib wrapper
# (with a .name attribute) before any log call is made — including the
# first log.info() in lifespan which previously crashed with:
#   AttributeError: 'PrintLogger' object has no attribute 'name'
configure_logging()
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # type: ignore[type-arg]
    """Pre-load heavy models at startup so the first call isn't slow."""
    cfg = get_settings()
    log.info("telephony_starting", host=cfg.server_host, port=cfg.server_port)

    # Pre-load VAD model (shared class attribute — loaded once)
    log.info("preloading_vad")
    SileroVAD._load_model()

    # Pre-load Whisper model
    log.info("preloading_whisper")
    FasterWhisperSTT()._load()

    if not cfg.hospital_id:
        log.error(
            "hospital_id_not_set",
            hint="set MEDNEXA_TEL_HOSPITAL_ID to the hospital's UUID; calls cannot be logged",
        )
    if not cfg.backend_api_key:
        log.warning(
            "backend_api_key_not_set",
            hint="set MEDNEXA_TEL_BACKEND_API_KEY (the backend's MEDNEXA_SERVICE_API_KEY); "
            "an authenticated backend rejects call logs without it",
        )
    if cfg.twilio_auth_token and not cfg.transfer_phone_number:
        log.warning(
            "transfer_phone_number_not_set",
            hint="set MEDNEXA_TEL_TRANSFER_PHONE_NUMBER so callers who ask for a person "
            "are connected to staff (otherwise they are asked to call reception)",
        )

    # Health-check backend
    async with BackendClient() as client:
        healthy = await client.health_check()
    if not healthy:
        log.warning("backend_unreachable", url=cfg.backend_url)
    else:
        log.info("backend_connected", url=cfg.backend_url)

    log.info("telephony_ready")
    yield

    log.info("telephony_shutting_down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MedNexa Telephony",
        description="Voice/Telephony pipeline — Part 3",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Twilio webhook + media stream
    app.include_router(twilio_router)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["system"])
    async def health() -> JSONResponse:
        async with BackendClient() as client:
            backend_ok = await client.health_check()
        hospital_configured = bool(get_settings().hospital_id)
        return JSONResponse(
            {
                "status": "ok" if backend_ok and hospital_configured else "degraded",
                "backend_connected": backend_ok,
                "hospital_configured": hospital_configured,
            }
        )

    # ── Mobile / Web Phone Test Page ──────────────────────────────────────────
    @app.get("/call", response_class=HTMLResponse)
    async def call_page() -> HTMLResponse:
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MedNexa phone</title>
    <style>
        :root {
            --bg: #f6f7f5; --card: #ffffff; --ink: #1d2320; --muted: #5d6762; --line: #dde1dd;
            --green: #1e6b5c; --amber: #9a6700; --blue: #2457a6; --red: #b42318;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #121513; --card: #1a1e1b; --ink: #eceeec; --muted: #9aa39e; --line: #2c322e;
                --green: #5fb39f; --amber: #d6a53a; --blue: #7aa5ee; --red: #f0877c;
            }
        }
        * { box-sizing: border-box; }
        body {
            margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
            background: var(--bg); color: var(--ink);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        main {
            width: 100%; max-width: 380px; background: var(--card); border: 1px solid var(--line);
            border-radius: 12px; padding: 28px 24px; text-align: center;
        }
        h1 { margin: 0 0 4px; font-size: 20px; }
        .sub { margin: 0 0 24px; color: var(--muted); font-size: 14px; }
        .hidden { display: none !important; }
        .start {
            font: inherit; font-size: 17px; font-weight: 600; padding: 14px 32px; border-radius: 8px;
            cursor: pointer; border: 0; background: var(--green); color: #fff;
        }
        .state {
            margin: 4px 0 18px; padding: 18px 12px; border-radius: 8px; border: 2px solid var(--line);
            transition: border-color .15s;
        }
        .state b { display: block; font-size: 20px; }
        .state span { font-size: 14px; color: var(--muted); }
        .state[data-s="listening"] { border-color: var(--green); }
        .state[data-s="listening"] b { color: var(--green); }
        .state[data-s="hearing"] { border-color: var(--green); background: color-mix(in srgb, var(--green) 10%, transparent); }
        .state[data-s="hearing"] b { color: var(--green); }
        .state[data-s="thinking"] { border-color: var(--blue); }
        .state[data-s="thinking"] b { color: var(--blue); }
        .state[data-s="speaking"] { border-color: var(--amber); }
        .state[data-s="speaking"] b { color: var(--amber); }
        .meter { height: 8px; border-radius: 4px; background: var(--line); overflow: hidden; margin: 0 0 6px; }
        .meter i { display: block; height: 100%; width: 0; background: var(--green); transition: width 60ms linear; }
        .meter-label { font-size: 12px; color: var(--muted); margin-bottom: 20px; }
        .end {
            font: inherit; font-size: 16px; font-weight: 600; padding: 12px 28px; border-radius: 8px;
            cursor: pointer; border: 0; background: var(--red); color: #fff;
        }
        .note { margin: 18px 0 0; font-size: 13px; color: var(--muted); line-height: 1.5; }
        .error { color: var(--red); font-size: 14px; margin-top: 14px; }
    </style>
</head>
<body>
<main>
    <h1>MedNexa Hospital</h1>
    <p class="sub" id="sub">AI receptionist</p>

    <section id="pick">
        <button class="start" onclick="startCall()">Start call</button>
    </section>

    <section id="live" class="hidden">
        <div class="state" id="state" data-s="speaking" aria-live="polite">
            <b id="stateTitle">Connecting…</b><span id="stateHint"></span>
        </div>
        <div class="meter"><i id="level"></i></div>
        <div class="meter-label" id="meterLabel">Microphone</div>
        <button class="end" onclick="stopCall()">End call</button>
    </section>

    <p class="note" id="note">Use headphones if you can: it stops the receptionist hearing itself.</p>
    <p class="error hidden" id="err"></p>
</main>

<script>
    const TEXT = {
        connecting: ["Connecting…", ""],
        speaking: ["Receptionist is speaking", "Please wait, your microphone is off"],
        listening: ["Your turn: speak now", "The receptionist is listening"],
        hearing: ["Hearing you…", "Keep going, pause when you are done"],
        thinking: ["Thinking…", "Please wait for the reply"],
    };
    const SPEECH_LEVEL = 0.02;     // mic level (0-1) that counts as the caller speaking
    const ECHO_TAIL = 0.7;         // seconds the mic stays off after the receptionist stops

    let ws, audioContext, micStream, processor;
    let isCalling = false, nextPlayTime = 0, serverThinking = false, shown = "";

    const $ = (id) => document.getElementById(id);

    function show(state) {
        if (state === shown) return;
        shown = state;
        const [title, hint] = TEXT[state];
        $("state").dataset.s = state;
        $("stateTitle").textContent = title;
        $("stateHint").textContent = hint;
    }

    async function startCall() {
        $("err").classList.add("hidden");
        $("pick").classList.add("hidden");
        $("live").classList.remove("hidden");
        $("sub").textContent = "Call in progress";
        show("connecting");
        try {
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            nextPlayTime = audioContext.currentTime;
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            ws = new WebSocket(`${protocol}//${location.host}/ws/call?phone=%2B919876543210&lang=en`);
            ws.binaryType = "arraybuffer";
            ws.onopen = () => { isCalling = true; show("speaking"); setupMic(); };
            ws.onmessage = (e) => {
                if (e.data instanceof ArrayBuffer) playPcm(e.data);
                else serverThinking = JSON.parse(e.data).state === "thinking";
            };
            ws.onclose = ws.onerror = () => isCalling && stopCall();
        } catch (err) {
            fail("Microphone error: " + err.message);
        }
    }

    function setupMic() {
        const source = audioContext.createMediaStreamSource(micStream);
        processor = audioContext.createScriptProcessor(512, 1, 1);
        processor.onaudioprocess = (e) => {
            if (!isCalling || !ws || ws.readyState !== WebSocket.OPEN) return;
            const input = e.inputBuffer.getChannelData(0);
            const now = audioContext.currentTime;
            const playing = nextPlayTime > now;
            // Half duplex: while the receptionist works out or speaks its reply (and for a
            // moment after), send silence instead of the microphone, so neither background
            // noise nor its own voice is taken for the caller.
            const muted = serverThinking || playing || now < nextPlayTime + ECHO_TAIL;

            let sum = 0;
            for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
            const level = muted ? 0 : Math.sqrt(sum / input.length);
            $("level").style.width = Math.min(100, level * 600) + "%";

            if (serverThinking && !playing) show("thinking");
            else if (muted) show("speaking");
            else show(level > SPEECH_LEVEL ? "hearing" : "listening");

            const pcm16 = new Int16Array(input.length);
            if (!muted) {
                for (let i = 0; i < input.length; i++) {
                    const s = Math.max(-1, Math.min(1, input[i]));
                    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
                }
            }
            ws.send(pcm16.buffer);
        };
        source.connect(processor);
        processor.connect(audioContext.destination);
    }

    function playPcm(buffer) {
        if (!audioContext) return;
        const int16 = new Int16Array(buffer);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
        const audioBuffer = audioContext.createBuffer(1, float32.length, 16000);
        audioBuffer.getChannelData(0).set(float32);
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        const now = audioContext.currentTime;
        if (nextPlayTime < now) nextPlayTime = now;
        source.start(nextPlayTime);
        nextPlayTime += audioBuffer.duration;
    }

    function fail(message) {
        stopCall();
        $("err").textContent = message;
        $("err").classList.remove("hidden");
    }

    function stopCall() {
        isCalling = false;
        serverThinking = false;
        if (processor) { processor.disconnect(); processor = null; }
        if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
        if (ws) { const s = ws; ws = null; s.close(); }
        if (audioContext) { audioContext.close(); audioContext = null; }
        shown = "";
        $("live").classList.add("hidden");
        $("pick").classList.remove("hidden");
        $("sub").textContent = "AI receptionist";
    }
</script>
</body>
</html>"""  # noqa: E501
        return HTMLResponse(content=html)

    # ── Local WebSocket test bridge ───────────────────────────────────────────
    # Connect with a raw WebSocket client and stream raw 16 kHz PCM audio.
    # Useful for integration tests without Twilio.
    @app.websocket("/ws/call")
    async def ws_call(websocket: WebSocket) -> None:
        """Raw PCM WebSocket bridge for local integration testing.

        Protocol:
          Client → Server: raw int16 LE PCM bytes (16 kHz mono)
          Server → Client: raw int16 LE PCM bytes (TTS responses)
          Server → Client: text {"state": "thinking" | "listening"} as the turn changes
          Session lifecycle: auto-start on connect, auto-end on disconnect.
        """
        from telephony.pipeline import CallPipeline

        await websocket.accept()
        cfg = get_settings()
        # Without ?phone=..., the call is logged as from a withheld number.
        caller_phone = websocket.query_params.get("phone", "anonymous")
        # The caller picks English or Hindi on the page; anything else means "detect it".
        language = websocket.query_params.get("lang")
        language = language if language in ("en", "hi") else None

        async with BackendClient() as client:
            session_id = await client.start_call(cfg.hospital_id, caller_phone)

        log.info("ws_call_connected", session_id=session_id, caller=caller_phone)

        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2000)

        async def receive_loop() -> None:
            try:
                while True:
                    chunk = await websocket.receive_bytes()
                    if not chunk:
                        break
                    if not pipeline.listening:
                        continue  # noise while the reply is worked out
                    try:
                        audio_queue.put_nowait(chunk)
                    except asyncio.QueueFull:
                        with contextlib.suppress(Exception):
                            audio_queue.get_nowait()
                        with contextlib.suppress(Exception):
                            audio_queue.put_nowait(chunk)
            except WebSocketDisconnect:
                pass
            except Exception:
                log.exception("ws_receive_error")
            finally:
                await audio_queue.put(b"")

        async def audio_gen() -> AsyncIterator[bytes]:
            while True:
                chunk = await audio_queue.get()
                if not chunk:
                    return
                yield chunk

        async def send_audio(pcm: bytes) -> None:
            with contextlib.suppress(Exception):  # client may have disconnected
                await websocket.send_bytes(pcm)

        async def send_state(state: str) -> None:
            await websocket.send_text(json.dumps({"state": state}))

        pipeline = CallPipeline(
            session_id, caller_phone, send_audio, language=language, on_state=send_state
        )
        recv_task = asyncio.create_task(receive_loop())
        pipe_task = asyncio.create_task(pipeline.run(audio_gen()))

        done, pending = await asyncio.wait(
            [recv_task, pipe_task], return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()

        log.info("ws_call_ended", session_id=session_id)

    return app


app = create_app()

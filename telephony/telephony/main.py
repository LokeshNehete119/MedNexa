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
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MedNexa Phone Agent</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 16px;
        }
        .card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 24px;
            padding: 32px 24px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
            text-align: center;
        }
        .avatar {
            width: 80px;
            height: 80px;
            background: #0284c7;
            border-radius: 50%;
            margin: 0 auto 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            box-shadow: 0 0 20px rgba(56, 189, 248, 0.4);
        }
        h1 { margin: 0 0 4px; font-size: 22px; color: #f8fafc; }
        .sub { color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
        .status-pill {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 24px;
            background: #334155;
            color: #94a3b8;
        }
        .status-pill.connected { background: #065f46; color: #34d399; }
        .btn-call {
            background: #10b981;
            color: white;
            border: none;
            width: 72px;
            height: 72px;
            border-radius: 50%;
            font-size: 28px;
            cursor: pointer;
            margin: 0 auto 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 10px 15px -3px rgba(16, 185, 129, 0.4);
            transition: all 0.2s;
        }
        .btn-call.hangup {
            background: #ef4444;
            box-shadow: 0 10px 15px -3px rgba(239, 68, 68, 0.4);
        }
        .btn-label { font-size: 14px; font-weight: 600; color: #cbd5e1; margin-bottom: 20px; }
        .instructions {
            background: #0f172a;
            border-radius: 12px;
            padding: 14px;
            text-align: left;
            font-size: 13px;
            color: #94a3b8;
            line-height: 1.5;
        }
    </style>
</head>
<body>
<div class="card">
    <div class="avatar">🏥</div>
    <h1>MedNexa Hospital</h1>
    <div class="sub">AI Receptionist Voice Call</div>

    <div id="statusPill" class="status-pill">Ready to Call</div>

    <button id="callBtn" class="btn-call" onclick="toggleCall()">📞</button>
    <div id="btnLabel" class="btn-label">Tap to Call</div>

    <div class="instructions" id="instBox">
        💡 <b>Instructions:</b><br>
        1. Tap green button to start.<br>
        2. Allow microphone permission.<br>
        3. Talk directly into your phone (English or Hindi).
    </div>
</div>

<script>
    let ws = null;
    let audioContext = null;
    let micStream = null;
    let scriptProcessor = null;
    let isCalling = false;
    let nextPlayTime = 0;

    const callBtn = document.getElementById('callBtn');
    const statusPill = document.getElementById('statusPill');
    const btnLabel = document.getElementById('btnLabel');
    const instBox = document.getElementById('instBox');

    async function toggleCall() {
        if (!isCalling) {
            await startCall();
        } else {
            stopCall();
        }
    }

    async function startCall() {
        try {
            statusPill.textContent = "Connecting...";
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            audioContext = new AudioCtx({ sampleRate: 16000 });
            nextPlayTime = audioContext.currentTime;

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/call?phone=+919876543210`;

            ws = new WebSocket(wsUrl);
            ws.binaryType = "arraybuffer";

            ws.onopen = () => {
                isCalling = true;
                statusPill.className = "status-pill connected";
                statusPill.textContent = "🟢 Connected (Speak now)";
                callBtn.className = "btn-call hangup";
                btnLabel.textContent = "Tap to End Call";
                instBox.innerHTML =
                    "🎙️ <b>Call in progress:</b><br>Speak now! Receptionist is listening.";
                setupMic();
            };

            ws.onmessage = (event) => {
                if (event.data instanceof ArrayBuffer) {
                    playPcm(event.data);
                }
            };

            ws.onclose = () => stopCall();
            ws.onerror = () => stopCall();

        } catch (err) {
            alert("Microphone error: " + err.message);
            stopCall();
        }
    }

    function setupMic() {
        const source = audioContext.createMediaStreamSource(micStream);
        scriptProcessor = audioContext.createScriptProcessor(512, 1, 1);

        scriptProcessor.onaudioprocess = (e) => {
            if (!isCalling || !ws || ws.readyState !== WebSocket.OPEN) return;
            const input = e.inputBuffer.getChannelData(0);
            const pcm16 = new Int16Array(input.length);
            for (let i = 0; i < input.length; i++) {
                let s = Math.max(-1, Math.min(1, input[i]));
                pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            ws.send(pcm16.buffer);
        };

        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);
    }

    function playPcm(buffer) {
        if (!audioContext) return;
        const int16 = new Int16Array(buffer);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
            float32[i] = int16[i] / 32768.0;
        }

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

    function stopCall() {
        isCalling = false;
        statusPill.className = "status-pill";
        statusPill.textContent = "Call Ended";
        callBtn.className = "btn-call";
        btnLabel.textContent = "Tap to Call";
        instBox.innerHTML = "💡 <b>Call ended.</b> Tap the green button to call again.";

        if (scriptProcessor) { scriptProcessor.disconnect(); scriptProcessor = null; }
        if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
        if (ws) { ws.close(); ws = null; }
        if (audioContext) { audioContext.close(); audioContext = null; }
    }
</script>
</body>
</html>"""
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
          Session lifecycle: auto-start on connect, auto-end on disconnect.
        """
        from telephony.pipeline import CallPipeline

        await websocket.accept()
        cfg = get_settings()
        # Without ?phone=..., the call is logged as from a withheld number.
        caller_phone = websocket.query_params.get("phone", "anonymous")

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

        recv_task = asyncio.create_task(receive_loop())
        pipeline = CallPipeline(session_id, caller_phone, send_audio)
        pipe_task = asyncio.create_task(pipeline.run(audio_gen()))

        done, pending = await asyncio.wait(
            [recv_task, pipe_task], return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()

        log.info("ws_call_ended", session_id=session_id)

    return app


app = create_app()

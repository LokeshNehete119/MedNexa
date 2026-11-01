"""Telephony server: Twilio webhooks and media streams, the /call test page and its
WebSocket, and a health check.

    uvicorn telephony.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from telephony.api_client import BackendClient
from telephony.config import get_settings
from telephony.logging_setup import configure_logging, get_logger
from telephony.stt import FasterWhisperSTT
from telephony.twilio_handler import router as twilio_router
from telephony.vad import SileroVAD

# Before the first log call, which happens at import time in some modules.
configure_logging()
log = get_logger("main")

CALL_PAGE = Path(__file__).with_name("call.html")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # type: ignore[type-arg]
    """Load the speech models before the first call, not during it."""
    cfg = get_settings()
    log.info("telephony_starting", host=cfg.server_host, port=cfg.server_port)

    log.info("preloading_models")
    SileroVAD._load_model()
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
        description="Phone calls answered by the MedNexa AI receptionist",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(twilio_router)

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

    @app.get("/call", response_class=HTMLResponse)
    async def call_page() -> HTMLResponse:
        return HTMLResponse(CALL_PAGE.read_text(encoding="utf-8"))

    @app.websocket("/ws/call")
    async def ws_call(websocket: WebSocket) -> None:
        """A call over a WebSocket, used by the /call page.

        Both directions carry 16 kHz mono int16 PCM as binary frames. The server also
        sends text frames {"state": "thinking" | "listening"} as the turn changes.
        The call starts on connect and ends on disconnect.
        """
        from telephony.pipeline import CallPipeline

        await websocket.accept()
        cfg = get_settings()
        # Without ?phone=..., the call is logged as from a withheld number.
        caller_phone = websocket.query_params.get("phone", "anonymous")
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

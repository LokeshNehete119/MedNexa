"""Text to speech: Piper (local) or Microsoft Edge voices (online), as 16 kHz mono PCM.

Piper needs its binary (https://github.com/rhasspy/piper/releases) on PATH or in
MEDNEXA_TEL_PIPER_BINARY, and .onnx voices in MEDNEXA_TEL_PIPER_MODELS_DIR. Without
them, or if Piper fails, the Edge voices are used.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from telephony.audio_codec import resample
from telephony.config import get_settings
from telephony.logging_setup import get_logger

log = get_logger("tts")

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

# Used when a Piper voice has no readable .onnx.json (the rate of *-medium voices).
PIPER_DEFAULT_RATE = 22050

WAV_HEADER_BYTES = 44

# Audio is sent to the caller in 100 ms chunks.
CHUNK_MS = 100
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH


class PiperTTS:
    def __init__(self) -> None:
        cfg = get_settings()
        self._binary = cfg.piper_binary
        self._models_dir = Path(cfg.piper_models_dir)
        self._voices: dict[str, str] = {
            "en": cfg.piper_voice_en,
            "hi": cfg.piper_voice_hi,
        }

    def _voice_path(self, language: str) -> Path:
        voice_name = self._voices.get(language, self._voices["en"])
        return self._models_dir / f"{voice_name}.onnx"

    @staticmethod
    def _voice_sample_rate(voice: Path) -> int:
        """Native output rate of a Piper voice, from its <voice>.onnx.json config."""
        config = voice.with_name(voice.name + ".json")
        try:
            return int(json.loads(config.read_text())["audio"]["sample_rate"])
        except (OSError, KeyError, ValueError, TypeError):
            log.warning("piper_sample_rate_unknown", config=str(config), assumed=PIPER_DEFAULT_RATE)
            return PIPER_DEFAULT_RATE

    def _is_available(self) -> bool:
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        voice = self._voice_path(language)
        if not voice.exists():
            raise FileNotFoundError(f"Piper model not found: {voice}")

        cmd = [
            self._binary,
            "--model",
            str(voice),
            "--output-raw",  # raw PCM output
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw_out, raw_err = await proc.communicate(input=text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(f"Piper failed: {raw_err.decode()}")
        # piper --output-raw produces raw s16le PCM (no header) at the voice's own
        # rate (22050 Hz for *-medium voices); the pipeline plays 16 kHz.
        return resample(raw_out, self._voice_sample_rate(voice), SAMPLE_RATE)

    async def async_synthesize(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        pcm = await self.synthesize(text, language)
        for i in range(0, len(pcm), CHUNK_BYTES):
            yield pcm[i : i + CHUNK_BYTES]


class EdgeTTS:
    """Microsoft Edge neural voices. They return MP3, which needs ffmpeg to decode."""

    def __init__(self) -> None:
        cfg = get_settings()
        self._voices: dict[str, str] = {
            "en": cfg.edge_voice_en,
            "hi": cfg.edge_voice_hi,
        }

    def _voice(self, language: str) -> str:
        return self._voices.get(language, self._voices["en"])

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        import edge_tts  # type: ignore[import-untyped]
        from pydub import AudioSegment  # type: ignore[import-untyped]

        voice = self._voice(language)
        communicate = edge_tts.Communicate(text, voice)

        mp3_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])
        mp3_data = b"".join(mp3_chunks)

        if not mp3_data:
            return b""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_data)
            tmp_path = f.name

        audio = AudioSegment.from_mp3(tmp_path)
        audio = (
            audio.set_frame_rate(SAMPLE_RATE).set_channels(CHANNELS).set_sample_width(SAMPLE_WIDTH)
        )
        Path(tmp_path).unlink(missing_ok=True)  # noqa: ASYNC240 - tiny local temp file
        return audio.raw_data  # type: ignore[return-value]

    async def async_synthesize(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        pcm = await self.synthesize(text, language)
        for i in range(0, len(pcm), CHUNK_BYTES):
            yield pcm[i : i + CHUNK_BYTES]


class TTSEngine:
    """Piper when it is set up (checked once), otherwise or on failure Edge."""

    def __init__(self) -> None:
        cfg = get_settings()
        self._prefer_piper = cfg.tts_engine.lower() == "piper"
        self._piper = PiperTTS()
        self._edge = EdgeTTS()
        self._piper_ok: bool | None = None

    def _use_piper(self) -> bool:
        if not self._prefer_piper:
            return False
        if self._piper_ok is None:
            self._piper_ok = self._piper._is_available()
            if not self._piper_ok:
                log.warning("piper_not_found", fallback="edge-tts")
        return self._piper_ok

    async def speak(self, text: str, language: str = "en") -> bytes:
        """Return raw PCM for the given text. Uses Piper or Edge-TTS."""
        if not text.strip():
            return b""
        try:
            if self._use_piper():
                log.debug("tts_piper", lang=language, chars=len(text))
                return await self._piper.synthesize(text, language)
        except Exception as exc:
            log.warning("piper_failed", error=str(exc), fallback="edge-tts")
            self._piper_ok = False

        log.debug("tts_edge", lang=language, chars=len(text))
        return await self._edge.synthesize(text, language)

    async def stream(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        """Yield raw PCM chunks as they become available."""
        pcm = await self.speak(text, language)
        for i in range(0, len(pcm), CHUNK_BYTES):
            yield pcm[i : i + CHUNK_BYTES]

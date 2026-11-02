"""Text to speech: Piper (local) or Microsoft Edge voices (online), as 16 kHz mono PCM.

Piper needs its binary (https://github.com/rhasspy/piper/releases) on PATH or in
MEDNEXA_TEL_PIPER_BINARY, and .onnx voices in MEDNEXA_TEL_PIPER_MODELS_DIR. Without
them, or if Piper fails, the Edge voices are used.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from telephony.audio_codec import resample
from telephony.config import get_settings
from telephony.logging_setup import get_logger

log = get_logger("tts")

SAMPLE_RATE = 16000
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
        self._rate = cfg.edge_rate

    def _voice(self, language: str) -> str:
        return self._voices.get(language, self._voices["en"])

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        import edge_tts  # type: ignore[import-untyped]

        communicate = edge_tts.Communicate(text, self._voice(language), rate=self._rate)
        mp3_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])
        mp3_data = b"".join(mp3_chunks)
        if not mp3_data:
            return b""
        # Decoding runs ffmpeg: keep it off the event loop, which carries every live call.
        return await asyncio.to_thread(_decode_mp3, mp3_data)

    async def async_synthesize(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        pcm = await self.synthesize(text, language)
        for i in range(0, len(pcm), CHUNK_BYTES):
            yield pcm[i : i + CHUNK_BYTES]


def _decode_mp3(mp3: bytes) -> bytes:
    """MP3 to 16 kHz mono int16 PCM with ffmpeg (pydub can't be imported on Python 3.13+)."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        input=mp3,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode the audio: {result.stderr.decode()[:200]}")
    return result.stdout


def trim_silence(pcm: bytes, lead: float = 0.04, tail: float = 0.15) -> bytes:
    """Cut the silence TTS services put around every sentence (about a second in all), keeping
    a short natural gap, so sentences run on and replies start sooner."""
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
    if samples.size == 0:
        return pcm
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > max(100, int(samples.max()) // 50))
    if loud.size == 0:
        return pcm
    start = max(0, int(loud[0]) - int(lead * SAMPLE_RATE))
    end = min(samples.size, int(loud[-1]) + int(tail * SAMPLE_RATE))
    return samples[start:end].tobytes()


async def _retry_pause(attempt: int) -> None:
    await asyncio.sleep(0.4 * (attempt + 1))


class TTSUnavailable(RuntimeError):
    """No voice could produce the audio, even after retrying."""


_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")

# A full stop after these (or after a single initial, "A. Sharma") isn't the end of a sentence.
_ABBREVIATION = re.compile(r"(?:^|\s)(?:dr|mr|mrs|ms|prof|st|no|vs|a\.m|p\.m|[A-Za-z])\.$", re.I)


def split_sentences(text: str, min_chars: int = 30, max_parts: int = 4) -> list[str]:
    """Sentences to synthesise separately, so the first can play while the rest are made.
    Short ones are joined to their neighbour, and there are never more than `max_parts`."""
    parts: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        if not sentence:
            continue
        if parts and _ABBREVIATION.search(parts[-1]) or parts and len(parts[-1]) < min_chars:
            parts[-1] = f"{parts[-1]} {sentence}"
        else:
            parts.append(sentence)
    while len(parts) > 1 and (len(parts[-1]) < min_chars or len(parts) > max_parts):
        last = parts.pop()
        parts[-1] = f"{parts[-1]} {last}"
    return parts


class TTSEngine:
    """Piper when it is set up (checked once), otherwise or on failure Edge.

    Replies are spoken a sentence at a time, all made in parallel, so a long reply starts
    playing after its first sentence. Network failures are retried, and sentences already
    made are remembered (shared by all calls), so fixed phrases keep working briefly when
    the voice service can't be reached.
    """

    _cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    def __init__(self) -> None:
        cfg = get_settings()
        self._prefer_piper = cfg.tts_engine.lower() == "piper"
        self._retries = cfg.tts_retries
        self._timeout = cfg.tts_timeout_seconds
        self._cache_size = cfg.tts_cache_size
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

    async def _synthesize(self, text: str, language: str) -> bytes:
        try:
            if self._use_piper():
                log.debug("tts_piper", lang=language, chars=len(text))
                return await self._piper.synthesize(text, language)
        except Exception as exc:
            log.warning("piper_failed", error=str(exc), fallback="edge-tts")
            self._piper_ok = False
        log.debug("tts_edge", lang=language, chars=len(text))
        return await self._edge.synthesize(text, language)

    async def speak(self, text: str, language: str = "en") -> bytes:
        """Raw PCM for `text`; retried on failure, raising TTSUnavailable if it keeps failing."""
        if not re.search(r"\w", text):
            return b""
        key = (language, text)
        if (cached := self._cache.get(key)) is not None:
            self._cache.move_to_end(key)
            return cached
        last: Exception | None = None
        for attempt in range(1 + self._retries):
            try:
                async with asyncio.timeout(self._timeout):
                    pcm = await self._synthesize(text, language)
            except Exception as exc:
                last = exc
                log.warning("tts_attempt_failed", attempt=attempt + 1, error=repr(exc)[:160])
                await _retry_pause(attempt)
                continue
            pcm = trim_silence(pcm)
            self._cache[key] = pcm
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return pcm
        raise TTSUnavailable(f"speech synthesis failed: {last!r}") from last

    async def stream(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        """PCM chunks, starting as soon as the first sentence is ready."""
        tasks = [asyncio.create_task(self.speak(p, language)) for p in split_sentences(text)]
        try:
            for task in tasks:
                pcm = await task
                for i in range(0, len(pcm), CHUNK_BYTES):
                    yield pcm[i : i + CHUNK_BYTES]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def prewarm(self, phrases: dict[str, list[str]]) -> int:
        """Make and remember fixed phrases ({language: [text, ...]}); returns how many worked."""
        done = 0
        for language, texts in phrases.items():
            for text in texts:
                try:
                    await self.speak(text, language)
                    done += 1
                except TTSUnavailable:
                    log.warning("tts_prewarm_failed", text=text[:40])
        return done

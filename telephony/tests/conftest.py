"""pytest configuration for the telephony test suite.

Sets up async test infrastructure and overrides settings so that
tests never touch real external services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from telephony.config import TelephonySettings


@pytest.fixture(autouse=True)
def override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override settings for all tests so they never hit real services."""
    import telephony.config as cfg_module

    test_settings = TelephonySettings(
        backend_url="http://test-backend:8000",
        hospital_id="00000000-0000-0000-0000-000000000000",
        whisper_model_size="tiny",
        whisper_device="cpu",
        whisper_compute_type="int8",
        vad_threshold=0.5,
        vad_min_speech_ms=100,
        vad_min_silence_ms=200,
        tts_engine="edge",
        enable_recordings=False,
        call_timeout_seconds=60,
        silence_timeout_seconds=10,
    )
    monkeypatch.setattr(cfg_module, "_settings", test_settings)


@pytest.fixture(autouse=True)
def short_utterances_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test audio is a few KB; real utterances shorter than 0.3 s are ignored."""
    monkeypatch.setattr("telephony.pipeline.MIN_UTTERANCE_BYTES", 0)


@pytest.fixture()
def mock_vad(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace SileroVAD with a mock that returns configurable events."""
    vad = MagicMock()
    vad.in_speech = False
    vad.process_chunk.return_value = ["silence"]
    vad.reset.return_value = None
    monkeypatch.setattr("telephony.pipeline.SileroVAD", lambda: vad)
    return vad


@pytest.fixture()
def mock_stt(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace FasterWhisperSTT with a mock."""
    from telephony.stt import TranscriptionResult

    stt = MagicMock()
    stt.transcribe_bytes.return_value = TranscriptionResult(
        text="I'd like to book an appointment",
        language="en",
        confidence=0.9,
        duration_seconds=2.0,
    )
    monkeypatch.setattr("telephony.pipeline.FasterWhisperSTT", lambda: stt)
    return stt


@pytest.fixture()
def mock_tts(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace TTSEngine with a mock that streams one empty chunk."""

    async def fake_stream(text: str, lang: str) -> AsyncIterator[bytes]:
        yield b"\x00" * 100

    tts = MagicMock()
    tts.stream = fake_stream
    monkeypatch.setattr("telephony.pipeline.TTSEngine", lambda: tts)
    return tts


@pytest.fixture()
def mock_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace BackendClient with an async mock."""
    client = AsyncMock()
    client.append_log = AsyncMock()
    client.end_call = AsyncMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr("telephony.pipeline.BackendClient", lambda: client)
    return client


@pytest.fixture()
def mock_recorder(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace CallRecorder with a no-op mock."""
    recorder = MagicMock()
    recorder.enabled = False
    recorder.__enter__ = MagicMock(return_value=recorder)
    recorder.__exit__ = MagicMock(return_value=None)
    recorder.write = MagicMock()
    monkeypatch.setattr("telephony.pipeline.CallRecorder", lambda sid: recorder)
    return recorder

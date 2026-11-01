"""One phone call: caller audio -> VAD -> Whisper -> agent -> TTS -> caller.

The call handlers (Twilio media streams and the /call web page) feed audio into
``CallPipeline.run`` and play back what it sends through ``send_audio``.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from telephony.agent_interface import AgentInterface, create_agent
from telephony.api_client import BackendClient
from telephony.audio_utils import AudioProcessor, normalise_audio
from telephony.config import get_settings
from telephony.logging_setup import get_logger
from telephony.recording import CallRecorder
from telephony.stt import FasterWhisperSTT
from telephony.tts import TTSEngine
from telephony.vad import SileroVAD

log = get_logger("pipeline")

SendAudioFn = Callable[[bytes], Awaitable[None]]
ClearAudioFn = Callable[[], Awaitable[None]]
TransferFn = Callable[[], Awaitable[bool]]
StateFn = Callable[[str], Awaitable[None]]

# Pipeline audio: 16 kHz mono int16 -> 32000 bytes per second of playback.
PCM_BYTES_PER_SECOND = 16000 * 2

# The agent says these only in its final reply.
_FAREWELL = re.compile(r"\bgood\s?-?bye\b|\bbye\b|अलविदा|धन्यवाद[\s,।!]*नमस्ते", re.IGNORECASE)

# What Whisper writes for breathing, clicks or background noise: never a caller's words.
_NOISE_TRANSCRIPT = re.compile(
    r"^[\W_]*(you|uh+|um+|hmm+|mm+|ah+|thanks for watching!?|subtitles by .*)?[\W_]*$",
    re.IGNORECASE,
)

# Said when the agent hands over to staff but the call can't be transferred.
_NO_TRANSFER = {
    "en": "I'm sorry, I can't connect you to our staff on this line. "
    "Please call the hospital reception directly. Goodbye!",
    "hi": "माफ़ कीजिए, इस लाइन पर स्टाफ़ से जोड़ना संभव नहीं है। कृपया अस्पताल के रिसेप्शन पर सीधे कॉल करें। नमस्ते!",
}

# 30 s of audio: an utterance is cut off here if VAD never hears it end.
MAX_UTTERANCE_BYTES = PCM_BYTES_PER_SECOND * 30


class CallPipeline:
    """One inbound call, from the greeting to the end of the call.

    ``session_id`` is the backend call session the transcript is written to.
    ``clear_audio`` drops audio already queued on the caller's side (barge-in),
    ``transfer`` connects the caller to staff and returns False if it couldn't,
    and ``on_state`` is told "thinking" / "listening" as the turn changes.
    ``language`` ("en" or "hi") fixes the call's language; left unset, it is
    detected from every utterance.
    """

    def __init__(
        self,
        session_id: str,
        caller_phone: str,
        send_audio: SendAudioFn,
        *,
        clear_audio: ClearAudioFn | None = None,
        transfer: TransferFn | None = None,
        agent: AgentInterface | None = None,
        language: str | None = None,
        on_state: StateFn | None = None,
    ) -> None:
        cfg = get_settings()
        self.session_id = session_id
        self.caller_phone = caller_phone
        self._send_audio = send_audio
        self._clear_audio = clear_audio
        self._transfer = transfer
        self._on_state = on_state
        self._cfg = cfg

        self._vad = SileroVAD()
        self._stt = FasterWhisperSTT()
        self._tts = TTSEngine()
        self._processor = AudioProcessor()
        self._agent: AgentInterface = agent or create_agent(caller_phone, cfg.hospital_id)
        self._api = BackendClient()
        self._recorder = CallRecorder(session_id)

        self._language: str = language or "en"
        self._language_chosen = language is not None
        if self._language_chosen and hasattr(self._agent, "fixed_language"):
            self._agent.fixed_language = self._language  # greeting and replies stay in it
        self._utterance_buf: bytearray = bytearray()
        # Audio is sent faster than real time and buffered by the telephony side,
        # so "playing" lasts until the caller has actually heard it all.
        self._playback_until: float = 0.0
        self._barge_in_triggered = asyncio.Event()
        self._call_active = True
        self._busy = False  # between the end of the caller's turn and the reply
        self._start_time: float = 0.0
        self._last_speech_time: float = 0.0

    async def run(self, audio_stream: AsyncIterator[bytes]) -> None:
        """Returns when the caller hangs up, the call times out or the agent says goodbye."""
        self._start_time = time.monotonic()
        self._last_speech_time = self._start_time

        with self._recorder:
            if self._recorder.enabled:
                await self._speak(self._recorder.consent_prompt(self._language))
                await self._log("ASSISTANT", self._recorder.consent_prompt(self._language))

            greeting = await self._agent.get_greeting()
            await self._speak(greeting)
            await self._log("ASSISTANT", greeting)

            try:
                async with asyncio.timeout(self._cfg.call_timeout_seconds):
                    await self._process_stream(audio_stream)
            except TimeoutError:
                log.warning("call_timeout", session_id=self.session_id)
                timeout_msg = (
                    "I'm sorry, the call has exceeded the maximum duration. Goodbye!"
                    if self._language == "en"
                    else "मुझे खेद है, कॉल की अधिकतम अवधि समाप्त हो गई है। नमस्ते!"
                )
                await self._speak(timeout_msg)
            finally:
                await self._end_call()

    async def _process_stream(self, audio_stream: AsyncIterator[bytes]) -> None:
        async for raw_chunk in audio_stream:
            if not self._call_active:
                break

            if time.monotonic() - self._last_speech_time > self._cfg.silence_timeout_seconds:
                log.info("silence_timeout", session_id=self.session_id)
                silence_msg = (
                    "Are you still there? Goodbye!"
                    if self._language == "en"
                    else "क्या आप अभी भी वहाँ हैं? नमस्ते!"
                )
                await self._speak(silence_msg)
                break

            chunk = self._processor.process(raw_chunk)
            self._recorder.write(chunk)

            events = self._vad.process_chunk(chunk)
            speaking = "speech_start" in events or "speech" in events
            utterance_ends = "speech_end" in events

            if speaking:
                self._last_speech_time = time.monotonic()
                if self._cfg.barge_in_enabled and self._is_playing():
                    await self._interrupt_playback()

            # Keep each chunk once while an utterance is open. VAD works in 32 ms
            # frames, so a short chunk can carry no event at all mid-utterance,
            # and a long one can carry several.
            if speaking or utterance_ends or self._vad.in_speech:
                self._utterance_buf.extend(chunk)

            if utterance_ends or len(self._utterance_buf) > MAX_UTTERANCE_BYTES:
                await self._process_utterance()

    @property
    def listening(self) -> bool:
        """False while a reply is being worked out: audio arriving then is background
        noise to the caller's finished turn, and the call handlers drop it."""
        return self._call_active and not self._busy

    async def _set_state(self, state: str) -> None:
        if self._on_state is not None:
            with contextlib.suppress(Exception):  # the client may have gone
                await self._on_state(state)

    async def _process_utterance(self) -> None:
        if not self._utterance_buf:
            return
        self._busy = True
        await self._set_state("thinking")
        try:
            await self._respond()
        finally:
            self._busy = False
            await self._set_state("listening")

    async def _respond(self) -> None:
        """Transcribe the buffered utterance, call the agent, speak the response."""
        if not self._utterance_buf:
            return

        pcm = bytes(self._utterance_buf)
        self._utterance_buf.clear()
        self._vad.reset()

        t0 = time.monotonic()
        # Level the whole utterance (not per chunk) so quiet lines transcribe well.
        pcm = normalise_audio(pcm)
        # Whisper blocks: run it off the event loop so other calls keep flowing.
        hint = self._language if self._language_chosen else None
        result = await asyncio.to_thread(self._stt.transcribe_bytes, pcm, language_hint=hint)
        stt_ms = int((time.monotonic() - t0) * 1000)

        text = result.text.strip()
        if self._is_noise(text, result.confidence):
            # Answering noise makes the receptionist talk over a quiet caller.
            log.info(
                "utterance_ignored",
                session_id=self.session_id,
                text=text[:40],
                confidence=round(result.confidence, 2),
            )
            return

        if result.language != self._language:
            log.info(
                "language_switch",
                session_id=self.session_id,
                from_lang=self._language,
                to_lang=result.language,
            )
            self._language = result.language

        log.info(
            "utterance_transcribed",
            session_id=self.session_id,
            text=text[:80],
            lang=self._language,
            stt_ms=stt_ms,
        )

        await self._log("USER", text)

        # The silence timer restarts around the reply, so a slow model or a long
        # reply isn't counted as the caller going quiet.
        self._last_speech_time = time.monotonic()
        t1 = time.monotonic()
        response = await self._agent.process(text, self._language)
        agent_ms = int((time.monotonic() - t1) * 1000)

        log.info(
            "agent_responded",
            session_id=self.session_id,
            response=response[:80],
            agent_ms=agent_ms,
        )

        await self._log("ASSISTANT", response)
        await self._speak(response, language=self._language)
        self._last_speech_time = time.monotonic()

        if getattr(self._agent, "escalated", False):
            await self._hand_over()
        elif self._is_farewell(response):
            self._call_active = False

    async def _hand_over(self) -> None:
        """The agent asked for a person: connect the caller to staff, or tell them how
        to reach staff. Either way the AI's part of the call is over."""
        self._call_active = False
        # Let the caller hear the agent's "please stay on the line" before moving the call.
        await asyncio.sleep(max(0.0, self._playback_until - time.monotonic()))
        if self._transfer is not None and await self._transfer():
            return
        message = _NO_TRANSFER.get(self._language, _NO_TRANSFER["en"])
        await self._speak(message)
        await self._log("ASSISTANT", message)

    def _is_playing(self) -> bool:
        return time.monotonic() < self._playback_until

    async def _interrupt_playback(self) -> None:
        """Stop the current reply: no more chunks, and drop what is already queued."""
        self._barge_in_triggered.set()
        self._playback_until = 0.0
        log.debug("barge_in", session_id=self.session_id)
        if self._clear_audio is not None:
            await self._clear_audio()

    async def _speak(self, text: str, language: str | None = None) -> None:
        lang = language or self._language
        self._barge_in_triggered.clear()

        t0 = time.monotonic()
        try:
            async for chunk in self._tts.stream(text, lang):
                if self._barge_in_triggered.is_set():
                    log.debug("tts_interrupted", session_id=self.session_id)
                    break
                await self._send_audio(chunk)
                start = max(self._playback_until, time.monotonic())
                self._playback_until = start + len(chunk) / PCM_BYTES_PER_SECOND
        finally:
            tts_ms = int((time.monotonic() - t0) * 1000)
            log.debug("tts_done", tts_ms=tts_ms, lang=lang)

    async def _log(self, role: str, content: str) -> None:
        await self._api.append_log(self.session_id, role, content)

    async def _end_call(self) -> None:
        try:
            summary = await self._agent.get_summary()
        except Exception:
            log.exception("agent_summary_failed", session_id=self.session_id)
            summary = None
        # The stub agent has no outcome of its own.
        await self._api.end_call(
            self.session_id,
            outcome=getattr(self._agent, "call_outcome", "OTHER"),
            summary=summary,
            language_detected=self._language,
            escalated_to_human=bool(getattr(self._agent, "escalated", False)),
        )
        await self._api.aclose()
        log.info("pipeline_done", session_id=self.session_id)

    def _is_noise(self, text: str, confidence: float) -> bool:
        return (
            bool(_NOISE_TRANSCRIPT.match(text)) or confidence < self._cfg.min_transcript_confidence
        )

    @staticmethod
    def _is_farewell(text: str) -> bool:
        """Did the agent close the call? Only explicit closing phrases count: words
        like "धन्यवाद" (thank you) or "take care" also occur mid-conversation."""
        return bool(_FAREWELL.search(text))

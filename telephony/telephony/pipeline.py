"""One phone call: caller audio -> VAD -> Whisper -> agent -> TTS -> caller.

The call handlers (Twilio media streams and the /call web page) feed audio into
``CallPipeline.run`` and play back what it sends through ``send_audio``. A call must
survive a failed speech, voice or model step: each is retried or answered with a short
apology, and the call only ends when the caller or the agent ends it.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

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
EventFn = Callable[[dict[str, Any]], Awaitable[None]]

# Pipeline audio: 16 kHz mono int16 -> 32000 bytes per second of playback.
PCM_BYTES_PER_SECOND = 16000 * 2

# Kept from before speech is detected: VAD needs a few frames to be sure, and without
# them the first syllable of every sentence is cut off.
PREROLL_BYTES = PCM_BYTES_PER_SECOND * 3 // 10

# Shorter than this can't be words (a click or a cough).
MIN_UTTERANCE_BYTES = PCM_BYTES_PER_SECOND * 3 // 10

# 30 s of audio: an utterance is cut off here if VAD never hears it end.
MAX_UTTERANCE_BYTES = PCM_BYTES_PER_SECOND * 30

# Longest the end of a call waits for the caller to hear the last words.
MAX_DRAIN_SECONDS = 20.0

# The agent says these only in its final reply.
_FAREWELL = re.compile(r"\bgood\s?-?bye\b|\bbye\b|अलविदा|धन्यवाद[\s,।!]*नमस्ते", re.IGNORECASE)

# What Whisper writes for breathing, clicks or background noise: never a caller's words.
_NOISE_TRANSCRIPT = re.compile(
    r"^[\W_]*(you|uh+|um+|hmm+|mm+|ah+|thanks for watching!?|subtitles by .*)?[\W_]*$",
    re.IGNORECASE,
)

# Phrases the pipeline says itself, by language.
PHRASES: dict[str, dict[str, str]] = {
    "filler": {"en": "One moment, please.", "hi": "एक पल रुकिए।"},
    "repeat": {
        "en": "Sorry, I didn't catch that. Could you say it again?",
        "hi": "माफ़ कीजिए, मुझे समझ नहीं आया। कृपया दोबारा कहिए।",
    },
    "agent_failed": {
        "en": "Sorry, something went wrong on my side. Could you say that again?",
        "hi": "माफ़ कीजिए, मेरी तरफ़ से कुछ गड़बड़ हो गई। कृपया दोबारा कहिए।",
    },
    "still_there": {"en": "Are you still there?", "hi": "क्या आप अभी भी वहाँ हैं?"},
    "silent_goodbye": {
        "en": "I can't hear you, so I'll end the call now. Goodbye!",
        "hi": "मुझे आपकी आवाज़ नहीं आ रही, इसलिए मैं कॉल समाप्त कर रही हूँ। नमस्ते!",
    },
    "timeout": {
        "en": "I'm sorry, the call has exceeded the maximum duration. Goodbye!",
        "hi": "मुझे खेद है, कॉल की अधिकतम अवधि समाप्त हो गई है। नमस्ते!",
    },
    "no_transfer": {
        "en": "I'm sorry, I can't connect you to our staff on this line. "
        "Please call the hospital reception directly. Goodbye!",
        "hi": "माफ़ कीजिए, इस लाइन पर स्टाफ़ से जोड़ना संभव नहीं है। "
        "कृपया अस्पताल के रिसेप्शन पर सीधे कॉल करें। नमस्ते!",
    },
}


def fixed_phrases() -> dict[str, list[str]]:
    """Everything said word for word, so it can be made before the first call and
    still be played if the voice service can't be reached later."""
    phrases = {lang: [p[lang] for p in PHRASES.values()] for lang in ("en", "hi")}
    try:
        from agent.agent import RETRY, TROUBLE  # type: ignore[import-not-found]
    except ImportError:
        return phrases
    for lang in phrases:
        phrases[lang] += [RETRY[lang], TROUBLE[lang]]
    return phrases


def _phrase(key: str, language: str) -> str:
    return PHRASES[key].get(language, PHRASES[key]["en"])


class CallPipeline:
    """One inbound call, from the greeting to the end of the call.

    ``session_id`` is the backend call session the transcript is written to.
    ``clear_audio`` drops audio already queued on the caller's side (barge-in),
    ``transfer`` connects the caller to staff and returns False if it couldn't, and
    ``on_event`` is sent {"state": "thinking" | "listening"}, {"transcript": {...}} for
    each line said, and {"speak": text} when a reply couldn't be turned into audio, so a
    client can show or voice it. ``language`` ("en" or "hi") fixes the call's language;
    left unset, it is detected from every utterance.
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
        on_event: EventFn | None = None,
    ) -> None:
        cfg = get_settings()
        self.session_id = session_id
        self.caller_phone = caller_phone
        self._send_audio = send_audio
        self._clear_audio = clear_audio
        self._transfer = transfer
        self._on_event = on_event
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
        self._preroll: deque[bytes] = deque()
        self._preroll_size = 0
        # Audio is sent faster than real time and buffered by the telephony side,
        # so "playing" lasts until the caller has actually heard it all.
        self._playback_until: float = 0.0
        self._barge_in_triggered = asyncio.Event()
        self._call_active = True
        self._busy = False  # between the end of the caller's turn and the reply
        self._unheard = 0  # utterances in a row that produced no words
        self._silence_prompted = False
        self._start_time: float = 0.0
        self._last_speech_time: float = 0.0

    async def run(self, audio_stream: AsyncIterator[bytes]) -> None:
        """Returns when the caller hangs up, the call times out or the agent says goodbye."""
        self._start_time = time.monotonic()
        self._last_speech_time = self._start_time

        with self._recorder:
            try:
                if self._recorder.enabled:
                    await self._speak(self._recorder.consent_prompt(self._language))
                    await self._log("ASSISTANT", self._recorder.consent_prompt(self._language))

                try:
                    greeting = await self._agent.get_greeting()
                except Exception:
                    log.exception("greeting_failed", session_id=self.session_id)
                    greeting = "Hello, thank you for calling. How can I help you today?"
                await self._speak(greeting)
                await self._log("ASSISTANT", greeting)

                try:
                    async with asyncio.timeout(self._cfg.call_timeout_seconds):
                        await self._process_stream(audio_stream)
                except TimeoutError:
                    log.warning("call_timeout", session_id=self.session_id)
                    await self._say("timeout")
            finally:
                # Also when the caller hangs up during the greeting: the call must be closed.
                await self._finish()

    async def _process_stream(self, audio_stream: AsyncIterator[bytes]) -> None:
        async for raw_chunk in audio_stream:
            if not self._call_active:
                break

            if await self._caller_went_quiet():
                break

            chunk = self._processor.process(raw_chunk)
            self._recorder.write(chunk)

            events = self._vad.process_chunk(chunk)
            speaking = "speech_start" in events or "speech" in events
            utterance_ends = "speech_end" in events

            if speaking:
                self._last_speech_time = time.monotonic()
                self._silence_prompted = False
                if self._cfg.barge_in_enabled and self._is_playing():
                    await self._interrupt_playback()

            # Keep each chunk once while an utterance is open. VAD works in 32 ms
            # frames, so a short chunk can carry no event at all mid-utterance,
            # and a long one can carry several.
            if speaking or utterance_ends or self._vad.in_speech:
                if not self._utterance_buf:
                    self._utterance_buf.extend(b"".join(self._preroll))
                    self._preroll.clear()
                    self._preroll_size = 0
                self._utterance_buf.extend(chunk)
            else:
                self._preroll.append(chunk)
                self._preroll_size += len(chunk)
                while self._preroll_size > PREROLL_BYTES:
                    self._preroll_size -= len(self._preroll.popleft())

            if utterance_ends or len(self._utterance_buf) > MAX_UTTERANCE_BYTES:
                await self._process_utterance()

    async def _caller_went_quiet(self) -> bool:
        """Ask "are you still there?" after half the silence timeout, and end the call after
        the other half. Time counts from when the caller last spoke or the last reply
        finished playing, so a long reply doesn't use up the caller's thinking time."""
        quiet_for = time.monotonic() - max(self._last_speech_time, self._playback_until)
        if quiet_for <= self._cfg.silence_timeout_seconds / 2:
            return False
        if not self._silence_prompted:
            log.info("silence_prompt", session_id=self.session_id)
            self._silence_prompted = True
            await self._say("still_there")
            return False
        log.info("silence_timeout", session_id=self.session_id)
        await self._say("silent_goodbye")
        self._call_active = False
        return True

    @property
    def listening(self) -> bool:
        """False while a reply is being worked out: audio arriving then is background
        noise to the caller's finished turn, and the call handlers drop it. Audio is still
        accepted once the call is over: reading the next chunk is how the loop notices."""
        return not self._busy

    async def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event is not None:
            with contextlib.suppress(Exception):  # the client may have gone
                await self._on_event(event)

    async def _process_utterance(self) -> None:
        if not self._utterance_buf:
            return
        self._busy = True
        await self._emit({"state": "thinking"})
        try:
            await self._respond()
        except Exception:
            # Whatever failed, the caller is still on the line: say sorry and carry on.
            log.exception("turn_failed", session_id=self.session_id)
            await self._say("agent_failed")
        finally:
            self._busy = False
            await self._emit({"state": "listening"})

    async def _respond(self) -> None:
        """Transcribe the buffered utterance, call the agent, speak the response."""
        pcm = bytes(self._utterance_buf)
        self._utterance_buf.clear()
        self._vad.reset()
        if len(pcm) < MIN_UTTERANCE_BYTES:
            return

        t0 = time.monotonic()
        # Level the whole utterance (not per chunk) so quiet lines transcribe well.
        pcm = normalise_audio(pcm)
        # Whisper blocks: run it off the event loop so other calls keep flowing.
        hint = self._language if self._language_chosen else None
        prompt = getattr(self._agent, "speech_hints", None)
        try:
            result = await asyncio.to_thread(
                self._stt.transcribe_bytes, pcm, language_hint=hint, prompt=prompt
            )
        except Exception:
            log.exception("stt_failed", session_id=self.session_id)
            await self._not_understood()
            return
        stt_ms = int((time.monotonic() - t0) * 1000)

        text = result.text.strip()
        if not text or _NOISE_TRANSCRIPT.match(text):
            log.info("utterance_ignored", session_id=self.session_id, text=text[:40])
            await self._not_understood()
            return
        self._unheard = 0

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
        response = await self._ask_agent(text)
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
        self._silence_prompted = False

        if getattr(self._agent, "escalated", False):
            await self._hand_over()
        elif self._is_farewell(response):
            self._call_active = False

    async def _ask_agent(self, text: str) -> str:
        """The agent's reply. If it takes a while, tell the caller to hold on."""
        task = asyncio.create_task(self._agent.process(text, self._language))
        try:
            done, _ = await asyncio.wait({task}, timeout=self._cfg.thinking_filler_seconds)
            if not done:
                await self._say("filler", log_it=False)
            return await task
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception:
            log.exception("agent_failed", session_id=self.session_id)
            return _phrase("agent_failed", self._language)

    async def _not_understood(self) -> None:
        """Nothing usable was heard. One such utterance may be noise, so stay quiet; two in a
        row means the caller is talking and not getting through."""
        self._unheard += 1
        if self._unheard >= 2:
            self._unheard = 0
            await self._say("repeat")

    async def _hand_over(self) -> None:
        """The agent asked for a person: connect the caller to staff, or tell them how
        to reach staff. Either way the AI's part of the call is over."""
        self._call_active = False
        # Let the caller hear the agent's "please stay on the line" before moving the call.
        await asyncio.sleep(max(0.0, self._playback_until - time.monotonic()))
        if self._transfer is not None and await self._transfer():
            return
        await self._say("no_transfer")

    def _is_playing(self) -> bool:
        return time.monotonic() < self._playback_until

    async def _interrupt_playback(self) -> None:
        """Stop the current reply: no more chunks, and drop what is already queued."""
        self._barge_in_triggered.set()
        self._playback_until = 0.0
        log.debug("barge_in", session_id=self.session_id)
        if self._clear_audio is not None:
            await self._clear_audio()

    async def _say(self, key: str, *, log_it: bool = True) -> None:
        text = _phrase(key, self._language)
        await self._speak(text)
        if log_it:
            await self._log("ASSISTANT", text)

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
        except Exception:
            # No voice: the call carries on, and a client that can speak gets the text.
            log.exception("tts_failed", session_id=self.session_id)
            await self._emit({"speak": text})
        finally:
            tts_ms = int((time.monotonic() - t0) * 1000)
            log.debug("tts_done", tts_ms=tts_ms, lang=lang)

    async def _log(self, role: str, content: str) -> None:
        if role in ("USER", "ASSISTANT"):
            await self._emit({"transcript": {"role": role.lower(), "text": content}})
        await self._api.append_log(self.session_id, role, content)

    async def _finish(self) -> None:
        """Let the caller hear the last words before the line closes, unless they hung up.
        The call is always closed in the backend, even if this is cancelled while waiting."""
        try:
            task = asyncio.current_task()
            if not (task and task.cancelling()):
                wait = min(self._playback_until - time.monotonic(), MAX_DRAIN_SECONDS)
                if wait > 0:
                    await asyncio.sleep(wait + 0.3)
        finally:
            await self._end_call()

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

    @staticmethod
    def _is_farewell(text: str) -> bool:
        """Did the agent close the call? Only explicit closing phrases count: words
        like "धन्यवाद" (thank you) or "take care" also occur mid-conversation."""
        return bool(_FAREWELL.search(text))

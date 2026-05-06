import asyncio
import aiohttp
import numpy as np

try:
    import soxr
    _HAVE_SOXR = True
except ImportError:
    _HAVE_SOXR = False

from typing import AsyncGenerator, Optional
from loguru import logger

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    LLMFullResponseStartFrame,
    CancelFrame,
    EndFrame,
)
from pipecat.services.tts_service import TTSService
from pipecat.services.settings import TTSSettings
from pipecat.processors.frame_processor import FrameDirection

# Predefined voices supported by pocket-tts natively (no wav required)
POCKET_TTS_PREDEFINED_VOICES = {
    'cosette', 'marius', 'javert', 'alba', 'jean', 'anna', 'vera',
    'fantine', 'charles', 'paul', 'eponine', 'azelma', 'george',
    'mary', 'jane', 'michael', 'eve', 'bill_boerst', 'peter_yearsley',
    'stuart_bell', 'caro_davy'
}


class PocketTTSService(TTSService):
    """
    Connects Dograh's Pipecat pipeline to a standalone pocket-tts server.
    - POST /tts with multipart form-data (text + voice_url)
    - soxr.resample per-chunk (anti-aliased 24kHz -> 16kHz, no thumps)
    - int16 PCM carry-over buffer for chunk-boundary alignment
    - Interruption handling: queue flush on UserStartedSpeakingFrame
    """

    def __init__(
        self,
        *,
        api_url: str = "http://pocket-tts:8000",
        voice_file: Optional[str] = None,
        voice_id: Optional[str] = "alba",
        use_enhanced_pipeline: bool = True,
        timeout: int = 300,
        **kwargs,
    ):
        settings = TTSSettings(
            model=kwargs.get("model", None),
            voice=voice_id or voice_file or "alba",
            language=kwargs.get("language", None),
        )
        super().__init__(sample_rate=16000, settings=settings, **kwargs)

        self._api_url = api_url.rstrip("/")
        self._voice_file = voice_file
        self._voice_id = voice_id or "alba"
        self._use_enhanced_pipeline = use_enhanced_pipeline
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._synthesis_lock = asyncio.Lock()

        # Byte-level carry-over for int16 chunk boundary alignment
        self._remainder_buffer = b""
        self._first_chunk = True

        # Interruption state
        self._interrupted = False
        self._stop_now = False
        self._current_response_id = 0

        if _HAVE_SOXR:
            logger.info("[PocketTTS] soxr available — using HQ anti-aliased resampling")
        else:
            logger.warning("[PocketTTS] soxr not available — falling back to linear interpolation")

    # ── Session ───────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def can_generate_metrics(self) -> bool:
        return True

    # ── Interruption frame interception ───────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, UserStartedSpeakingFrame):
            logger.info("[PocketTTS] User started speaking — flushing queue")
            self._interrupted = True
            self._stop_now = True
            self._current_response_id += 1
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            logger.info("[PocketTTS] User stopped speaking — synthesis re-enabled")
            self._interrupted = False
            self._stop_now = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._interrupted = False
            self._stop_now = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (CancelFrame, EndFrame)):
            self._interrupted = True
            self._stop_now = True
            await self.push_frame(frame, direction)
            return

        await super().process_frame(frame, direction)

    # ── Voice URL resolution ───────────────────────────────────────────────

    def _build_form(self, text: str) -> Optional[aiohttp.FormData]:
        if not text or not str(text).strip():
            return None

        clean_text = str(text).strip()
        target_voice = self._voice_id or self._voice_file or "alba"

        if target_voice.startswith("/voices/"):
            voice_url = f"http://voice-files{target_voice}"
        elif target_voice.startswith("/dataset/"):
            voice_url = f"http://voice-files{target_voice}"
        elif any(target_voice.startswith(p) for p in ("hf://", "http://", "https://")):
            voice_url = target_voice
        elif target_voice in POCKET_TTS_PREDEFINED_VOICES:
            voice_url = target_voice
        elif target_voice == "expresso":
            voice_url = "hf://kyutai/tts-voices/expresso/ex01-ex02_default_001_channel2_198s.wav"
        else:
            voice_url = target_voice

        form = aiohttp.FormData()
        form.add_field("text", clean_text)
        form.add_field("voice_url", voice_url)
        logger.debug(f"[PocketTTS] POST /tts  voice_url='{voice_url}'  text='{clean_text[:40]}'")
        return form

    # ── Resampling: soxr per-chunk (stateless, simple, no bugs) ──────────

    def _resample_chunk(self, chunk: bytes) -> bytes:
        """Resample one chunk of raw int16 PCM from 24kHz to 16kHz."""
        # Strip WAV header if present (first chunk sometimes has it)
        if chunk[:4] == b'RIFF':
            chunk = chunk[44:]

        try:
            # Re-join carry-over bytes from previous chunk boundary
            if self._remainder_buffer:
                chunk = self._remainder_buffer + chunk
                self._remainder_buffer = b""

            # int16 = 2 bytes per sample — trim to even length
            remainder = len(chunk) % 2
            if remainder:
                self._remainder_buffer = chunk[-remainder:]
                chunk = chunk[:-remainder]

            if len(chunk) == 0:
                return b""

            # Decode int16 PCM → float32
            audio_i16 = np.frombuffer(chunk, dtype=np.int16)
            audio_f32 = audio_i16.astype(np.float32) / 32768.0

            # Resample 24kHz → 16kHz
            if _HAVE_SOXR:
                resampled = soxr.resample(audio_f32, 24000, 16000, quality="HQ")
            else:
                old_len = len(audio_f32)
                new_len = int(old_len * 16000 / 24000)
                if new_len == 0:
                    return b""
                indices = np.linspace(0, old_len - 1, new_len)
                resampled = np.interp(indices, np.arange(old_len), audio_f32)

            if len(resampled) == 0:
                return b""

            # Gentle 4ms fade-in on the very first chunk of each utterance
            # Prevents a click if TTS starts at a non-zero sample value
            if self._first_chunk:
                fade_len = min(64, len(resampled))
                resampled[:fade_len] *= np.linspace(0.0, 1.0, fade_len)
                self._first_chunk = False

            return np.clip(resampled * 32767, -32768, 32767).astype(np.int16).tobytes()

        except Exception as e:
            logger.warning(f"[PocketTTS] Resample failed: {e}")
            return b""

    # ── Synthesis ─────────────────────────────────────────────────────────

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text or not text.strip():
            return

        my_response_id = self._current_response_id

        if self._interrupted:
            logger.info(f"[PocketTTS] Dropping (pre-interrupted): '{text[:50]}'")
            return

        self._stop_now = False
        logger.info(f"[PocketTTS] Synthesizing: '{text[:60]}'")

        async with self._synthesis_lock:
            if self._interrupted or my_response_id != self._current_response_id:
                logger.info(f"[PocketTTS] Dropping (interrupted while queued): '{text[:50]}'")
                return

            # CRITICAL: Register this context with the base class serialization queue
            # BEFORE yielding any frames. Without this, tts_process_generator's call to
            # append_to_audio_context() silently drops ALL frames (including audio).
            await self.create_audio_context(context_id)

            yield TTSStartedFrame(context_id=context_id)

            try:
                session = await self._get_session()
                form = self._build_form(text)

                if form is None:
                    yield TTSStoppedFrame(context_id=context_id)
                    return

                # Reset per-utterance state
                self._remainder_buffer = b""
                self._first_chunk = True

                async with session.post(
                    f"{self._api_url}/tts",
                    data=form,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[PocketTTS] HTTP {resp.status}: {body}")
                        return

                    async for chunk in resp.content.iter_chunked(1200):
                        if self._stop_now or my_response_id != self._current_response_id:
                            logger.info("[PocketTTS] Stopping mid-stream (interrupted)")
                            break

                        audio = self._resample_chunk(chunk)
                        if audio:
                            yield TTSAudioRawFrame(
                                audio=audio,
                                sample_rate=16000,
                                num_channels=1,
                                context_id=context_id,
                            )

            except asyncio.CancelledError:
                logger.info("[PocketTTS] CancelledError — synthesis cancelled by user")
                self._stop_now = True
                self._interrupted = True
                self._current_response_id += 1

            except Exception as e:
                logger.error(f"[PocketTTS] Error: {e}")
                yield ErrorFrame(error=str(e))

            finally:
                yield TTSStoppedFrame(context_id=context_id)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

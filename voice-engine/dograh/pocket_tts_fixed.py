import asyncio
import aiohttp
import numpy as np
from typing import AsyncGenerator, Optional, Dict
from loguru import logger

from pipecat.frames.frames import (
    AggregatedTextFrame,
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService
from pipecat.services.settings import TTSSettings

# Predefined voices for fallback
POCKET_TTS_PREDEFINED_VOICES = {
    'cosette', 'marius', 'javert', 'alba', 'jean', 'anna', 'vera',
    'fantine', 'charles', 'paul', 'eponine', 'azelma', 'george',
    'mary', 'jane', 'michael', 'eve', 'bill_boerst', 'peter_yearsley',
    'stuart_bell', 'caro_davy'
}

class PocketTTSService(TTSService):
    """
    Connects Dograh's Pipecat pipeline to a standalone pocket-tts server.
    - Guards against empty/None text in _build_payload (catches all paths).
    - Resamples 24000 Hz float32 â†’ 16000 Hz int16.
    """

    def __init__(
        self,
        *,
        api_url: str = "http://pocket-tts:8000",
        voice_file: Optional[str] = None,
        voice_id:   Optional[str] = "alba",
        use_enhanced_pipeline: bool = True,
        timeout:    int = 300,
        **kwargs,
    ):
        settings = TTSSettings(
            model=kwargs.get("model", None),
            voice=voice_id or voice_file or "alba",
            language=kwargs.get("language", None),
        )
        super().__init__(
            sample_rate=16000,
            settings=settings,
            **kwargs
        )
        self._api_url = api_url.rstrip("/")
        self._voice_file = voice_file
        self._voice_id = voice_id or "alba"
        self._use_enhanced_pipeline = use_enhanced_pipeline
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._synthesis_lock = asyncio.Lock()
        self._remainder_buffer = b""
        self._overlap_buffer: Optional[np.ndarray] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def can_generate_metrics(self) -> bool:
        return True

    def _build_payload(self, text: str) -> Optional[Dict]:
        """
        Returns None if text is empty/None â€” caller must check and skip.
        Never sends null text to pocket-tts.
        """
        if not text or not str(text).strip():
            return None

        clean_text = str(text).strip()
        voice_url = "alba"  # safe fallback
        
        # Priority:
        # 1. Specific local container path (e.g. /voices/recording_1.wav)
        # 2. Remote URL (hf://, http://, etc)
        # 3. Predefined voice ID
        
        target_voice = self._voice_id or self._voice_file or "alba"
        
        if target_voice.startswith("/voices/"):
            # The Pocket TTS HTTP endpoint rejects raw file paths.
            # We use the internal Nginx voice-files container to serve it via HTTP.
            voice_url = f"http://voice-files{target_voice}"
        elif target_voice.startswith("/app/"):
            voice_url = target_voice
        elif any(target_voice.startswith(p) for p in ("hf://", "http://", "https://")):
            voice_url = target_voice
        elif target_voice in POCKET_TTS_PREDEFINED_VOICES:
            voice_url = target_voice
        elif target_voice == "expresso":
             voice_url = "hf://kyutai/tts-voices/expresso/ex01-ex02_default_001_channel2_198s.wav"

        return {
            "text": clean_text,
            "voice_url": voice_url,
        }

    def _resample_24k_to_16k(self, chunk: bytes, is_final: bool = False) -> bytes:
        XFADE_LEN = 64

        # Handle flushing the final buffer at the end of the utterance
        if is_final:
            if self._overlap_buffer is not None:
                out = self._overlap_buffer.copy()
                # Final fade-out to prevent ending click
                fade_len = min(XFADE_LEN, len(out))
                if fade_len > 0:
                    out[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)
                self._overlap_buffer = None
                return self._to_int16_bytes(out)
            return b""

        # Strip 44-byte WAV header if present (only on the very first chunk)
        data = chunk
        if data.startswith(b'RIFF'):
            data = data[44:]

        try:
            # Prepend any carry-over bytes from the previous chunk (int16 alignment)
            if self._remainder_buffer:
                data = self._remainder_buffer + data
                self._remainder_buffer = b""

            # CRITICAL: server sends int16 PCM â€” each sample is 2 bytes.
            remainder = len(data) % 2
            if remainder:
                self._remainder_buffer = data[-remainder:]
                data = data[:-remainder]

            if len(data) == 0:
                return b""

            # Interpret as signed 16-bit PCM and convert to float32
            audio_i16 = np.frombuffer(data, dtype=np.int16)
            audio_f32 = audio_i16.astype(np.float32) / 32768.0

            # Resample 24kHz -> 16kHz
            old_len = len(audio_f32)
            new_len = int(old_len * 16000 / 24000)
            if new_len == 0:
                return b""

            indices = np.linspace(0, old_len - 1, new_len)
            resampled = np.interp(indices, np.arange(old_len), audio_f32)

            # Apply 1.2x volume boost
            resampled = resampled * 1.2

            # â”€â”€ OVERLAP-ADD CROSSFADE LOGIC â”€â”€
            if self._overlap_buffer is None:
                # First chunk of the utterance: Fade in
                fade_len = min(XFADE_LEN, len(resampled))
                if fade_len > 0:
                    resampled[:fade_len] *= np.linspace(0.0, 1.0, fade_len)
                
                # Keep the end for crossfading with the next chunk
                if len(resampled) > XFADE_LEN:
                    self._overlap_buffer = resampled[-XFADE_LEN:].copy()
                    return self._to_int16_bytes(resampled[:-XFADE_LEN])
                else:
                    self._overlap_buffer = resampled
                    return b""
            else:
                # Middle chunk: Crossfade the start of this chunk with the end of the last one
                xfade_len = min(XFADE_LEN, len(resampled))
                
                fade_in = np.linspace(0.0, 1.0, xfade_len)
                fade_out = np.linspace(1.0, 0.0, xfade_len)
                
                # Overlap-add the buffered samples with the beginning of the new ones
                resampled[:xfade_len] = (self._overlap_buffer[:xfade_len] * fade_out) + (resampled[:xfade_len] * fade_in)
                
                # Save the end of this chunk for the next cycle
                if len(resampled) > XFADE_LEN:
                    new_overlap = resampled[-XFADE_LEN:].copy()
                    out = resampled[:-XFADE_LEN]
                    self._overlap_buffer = new_overlap
                    return self._to_int16_bytes(out)
                else:
                    self._overlap_buffer = resampled # rare
                    return b""

        except Exception as e:
            logger.warning(f"[PocketTTS] Resample failed: {e}")
            return b""

    def _to_int16_bytes(self, audio_f32: np.ndarray) -> bytes:
        """Convert float32 array back to int16 PCM bytes."""
        return np.clip(audio_f32 * 32767, -32768, 32767).astype(np.int16).tobytes()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text or not text.strip():
            return

        logger.info(f"[PocketTTS] Synthesizing: '{text[:60]}...'")

        async with self._synthesis_lock:
            yield TTSStartedFrame(context_id=context_id)

            try:
                # Use a fresh session to ensure clean cancellation if needed
                # or reuse the shared one for performance. Dograh alignment 
                # suggests handling cancellation at the task level.
                session = await self._get_session()
                payload = self._build_payload(text)
                
                if payload is None:
                    yield TTSStoppedFrame(context_id=context_id)
                    return

                # Reset chunk-boundary carry-over for each new utterance
                self._remainder_buffer = b""
                self._overlap_buffer = None

                async with session.post(
                    f"{self._api_url}/tts",
                    data=payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[PocketTTS] HTTP {resp.status}: {body}")
                        return

                    async for chunk in resp.content.iter_chunked(1200):
                        # asyncio.CancelledError is thrown HERE by Pipecat
                        # when user interrupts â€” no manual flag needed
                        
                        audio = self._resample_24k_to_16k(chunk)
                        if audio:
                            yield TTSAudioRawFrame(
                                audio=audio,
                                sample_rate=16000,
                                num_channels=1,
                                context_id=context_id,
                            )

                    # Flush the remaining overlap buffer at the end of the text
                    final_audio = self._resample_24k_to_16k(b"", is_final=True)
                    if final_audio:
                        yield TTSAudioRawFrame(
                            audio=final_audio,
                            sample_rate=16000,
                            num_channels=1,
                            context_id=context_id,
                        )

            except asyncio.CancelledError:
                # THIS IS THE CORRECT INTERRUPT HANDLER for Dograh
                # Pipecat throws CancelledError into the task when
                # VAD detects user speech mid-TTS
                logger.info("[PocketTTS] âœ… Interrupted by user â€” synthesis cancelled")
                # DO NOT re-raise â€” let it fall through to TTSStoppedFrame

            except Exception as e:
                logger.error(f"[PocketTTS] Error: {e}")
                yield ErrorFrame(error=str(e))

            finally:
                # Always emit stop frame â€” pipeline needs this to clean up
                yield TTSStoppedFrame(context_id=context_id)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

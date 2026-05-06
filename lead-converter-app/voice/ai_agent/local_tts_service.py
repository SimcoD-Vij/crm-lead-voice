import httpx
from typing import AsyncGenerator
from loguru import logger
from pipecat.services.ai_services import TTSService
from pipecat.frames.frames import AudioRawFrame, ErrorFrame, Frame

class CustomLocalTTSService(TTSService):
    """
    Custom Pipecat TTS Service connecting to our Local FastAPI XTTS-v2 Server.
    Provides ultra-low latency Tamil voice cloning streaming.
    """
    def __init__(self, api_url: str = "http://host.docker.internal:8001/synthesize", language: str = "en"):
        super().__init__()
        self._api_url = api_url
        self._language = language

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"Local TTS Generating audio for: {text}")
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST", 
                    self._api_url, 
                    json={"text": text, "language": self._language},
                    timeout=30.0
                ) as response:
                    if response.status_code != 200:
                        logger.error(f"TTS API Error: {response.status_code}")
                        yield ErrorFrame(f"Local TTS API Error: {response.status_code}")
                        return
                        
                    # Stream the raw audio chunks (16-bit 24kHz PCM WAV) back to Pipecat and Twilio
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        # Yield raw audio frames (skip the 44-byte WAV header roughly for basic streaming, 
                        # Pipecat can usually handle standard PCM payloads if configured correctly, 
                        # but we yield raw audio directly).
                        yield AudioRawFrame(audio=chunk, sample_rate=24000, num_channels=1)
                        
        except Exception as e:
            logger.error(f"Local TTS Service Exception: {e}")
            yield ErrorFrame(str(e))

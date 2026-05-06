"""
QwenTTSService — Pipecat TTS service for the local Qwen3-TTS voice-cloning server.
Using WebSocket streaming for minimum latency.
"""
import asyncio
import base64
import json
from typing import Optional, AsyncGenerator

from loguru import logger

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    StartFrame,
    EndFrame,
    CancelFrame,
)
from pipecat.services.tts_service import WebsocketTTSService, TTSSettings

try:
    import websockets
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use Qwen TTS streaming, you need to `pip install websockets`.")
    raise Exception(f"Missing module: {e}")


class QwenTTSService(WebsocketTTSService):
    """
    TTS service that calls the local Qwen3-TTS voice-cloning API (server.py) over WebSocket.
    Configuration in Dograh:
      - api_url : e.g. "ws://host.docker.internal:8765/voice/stream"
      - voice   : ignored
      - api_key : optional
    """

    def __init__(
        self,
        *,
        api_url: str,
        voice_id: str = None,
        api_key: str = None,
        language: str = "English",
        sample_rate: int = 24000,
        settings: Optional[TTSSettings] = None,
        **kwargs,
    ):
        if not settings:
            settings = TTSSettings(
                model="qwen3-tts", 
                voice=voice_id or "custom", 
                language=language or "English"
            )
            
        super().__init__(
            push_text_frames=False,
            push_stop_frames=True,
            pause_frame_processing=True,
            sample_rate=sample_rate,
            settings=settings,
            **kwargs,
        )
        
        if api_url and api_url.startswith("http"):
            api_url = api_url.replace("http", "ws")
        
        if api_url and not api_url.endswith("/voice/stream"):
            if api_url.endswith("/generate"):
                api_url = api_url.replace("/generate", "/voice/stream")
            else:
                api_url = api_url.rstrip("/") + "/voice/stream"

        self._api_url = api_url
        self._api_key = api_key
        self._language = language

        # WebSocket tasks
        self._receive_task = None
        self._accumulated_text = ""

    def can_generate_metrics(self) -> bool:
        return True

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            if not self._api_url:
                raise ValueError("api_url is not configured")

            url = self._api_url
            if self._api_key:
                url += f"?api_key={self._api_key}"

            logger.debug(f"Connecting to Qwen TTS WebSocket at {url}")
            self._websocket = await websocket_connect(url)
            
            logger.info(f"Successfully connected to Qwen TTS service at {url}")
            await self._websocket.send(json.dumps({"type": "config"}))

        except Exception as e:
            self._websocket = None
            logger.error(f"Failed to connect to Qwen TTS service: {e}")
            raise

    async def _disconnect_websocket(self):
        try:
            await self.stop_all_metrics()
            if self._websocket:
                logger.debug("Disconnecting from Qwen TTS service")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"Error disconnecting from Qwen TTS service: {e}")
        finally:
            await self.remove_active_audio_context()
            self._websocket = None

    async def _connect(self):
        await super()._connect()
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    async def _receive_messages(self):
        async for message in self._get_websocket():
            try:
                msg = json.loads(message)
                msg_type = msg.get("type")
                ctx_id = msg.get("context_id")

                if msg_type == "final":
                    logger.debug(f"Received final message for context {ctx_id}")
                    if ctx_id:
                        await self.remove_audio_context(ctx_id)
                    continue

                if ctx_id and not self.audio_context_available(ctx_id):
                    if self.get_active_audio_context_id() == ctx_id:
                        await self.create_audio_context(ctx_id)
                    else:
                        continue

                if msg_type == "audio":
                    try:
                        await self.stop_ttfb_metrics()
                        audio_data = msg.get("audio")
                        sr = msg.get("sample_rate", self.sample_rate)
                        if audio_data:
                            audio = base64.b64decode(audio_data)
                            logger.debug(f"Received audio chunk: {len(audio)} bytes for context {ctx_id}")
                            frame = TTSAudioRawFrame(audio, sr, 1, context_id=ctx_id)
                            effective_ctx_id = ctx_id or self.get_active_audio_context_id()
                            if effective_ctx_id:
                                await self.append_to_audio_context(effective_ctx_id, frame)
                    except Exception as e:
                        logger.error(f"Error handling audio from Qwen TTS: {e}")

                elif msg_type == "error":
                    error_msg = msg.get("message", "Unknown error")
                    logger.error(f"Qwen TTS reported error: {error_msg}")
                    await self.push_frame(TTSStoppedFrame())
                    await self.stop_all_metrics()
                    raise Exception(f"Qwen TTS error: {error_msg}")

            except asyncio.CancelledError:
                logger.debug("Qwen TTS receiving task cancelled")
                raise
            except Exception as e:
                logger.error(f"Critical error in Qwen TTS receive loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise

    async def _send_text(self, text: str, context_id: str):
        if self._websocket and context_id:
            msg = {
                "type": "synthesize",
                "text": text,
                "context_id": context_id,
                "language": self._language,
                "flush": True,
            }
            logger.debug(f"Sending text to Qwen TTS: '{text}' [ctx: {context_id}]")
            await self._websocket.send(json.dumps(msg))

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"{self}: Generating TTS [{text}]")

        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()

            try:
                if not self.audio_context_available(context_id):
                    await self.create_audio_context(context_id)
                    await self.start_ttfb_metrics()
                    yield TTSStartedFrame(context_id=context_id)

                    context_msg = {
                        "type": "create_context",
                        "context_id": context_id,
                    }
                    await self._websocket.send(json.dumps(context_msg))

                await self._send_text(text, context_id)
                self._accumulated_text += text
                await self.start_tts_usage_metrics(text)
            except Exception as e:
                yield TTSStoppedFrame(context_id=context_id)
                yield ErrorFrame(error=f"Unknown error occurred: {e}")
                return

            yield None

        except Exception as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")

    async def _close_context(self, context_id: str):
        if context_id and self._websocket:
            try:
                await self._websocket.send(
                    json.dumps({"type": "close_context", "context_id": context_id})
                )
            except Exception as e:
                logger.error(f"Error closing context: {e}")

        if self._accumulated_text:
            await self.start_tts_usage_metrics(self._accumulated_text)
            self._accumulated_text = ""

    async def on_audio_context_interrupted(self, context_id: str):
        await self._close_context(context_id)

    async def on_audio_context_completed(self, context_id: str):
        await self._close_context(context_id)

    async def flush_audio(self, context_id: Optional[str] = None):
        flush_id = context_id or self.get_active_audio_context_id()
        if not flush_id or not self._websocket:
            return
        msg = {"context_id": flush_id, "flush": True}
        await self._websocket.send(json.dumps(msg))

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

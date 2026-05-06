# ---------------------------------------------------------
# voice/ai_agent_client.py
# AI Agent Client - replaces voice/ai_agent_client.js
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Union

import httpx
import websockets

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AI_AGENT_CLIENT")

class AIAgentClient:
    def __init__(self, service_url: Optional[str] = None):
        self.service_url = service_url or os.getenv('AI_AGENT_SERVICE_URL', 'http://localhost:8001')
        self.ws_url = self.service_url.replace('http://', 'ws://').replace('https://', 'wss://')
        self.active_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.callbacks: Dict[str, list[Callable]] = {
            'message': [],
            'error': [],
            'close': []
        }

    def on(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    async def _emit(self, event: str, *args):
        for callback in self.callbacks.get(event, []):
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)

    async def initialize_call(self, call_id: str, phone_number: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize a new AI voice call."""
        options = options or {}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.service_url}/call/init", json={
                    "call_id": call_id,
                    "phone_number": phone_number,
                    "caller_name": options.get("callerName"),
                    "context": options.get("context")
                })
                response.raise_for_status()
                data = response.json()
                logger.info(f"[{call_id}] AI call initialized: {data}")
                return data
        except Exception as e:
            logger.error(f"[{call_id}] Failed to initialize AI call: {e}")
            raise

    async def get_call_status(self, call_id: str) -> Dict[str, Any]:
        """Get current status of a call."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.service_url}/call/{call_id}/status")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"[{call_id}] Failed to get call status: {e}")
            raise

    async def end_call(self, call_id: str) -> Dict[str, Any]:
        """End an active call."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.service_url}/call/{call_id}/end")
                response.raise_for_status()
                
                # Close WebSocket if exists
                if call_id in self.active_connections:
                    ws = self.active_connections.pop(call_id)
                    await ws.close()
                
                data = response.json()
                logger.info(f"[{call_id}] AI call ended: {data}")
                return data
        except Exception as e:
            logger.error(f"[{call_id}] Failed to end call: {e}")
            raise

    async def connect_websocket(self, call_id: str):
        """Connect to AI agent via WebSocket for real-time communication."""
        ws_url = f"{self.ws_url}/ws/call/{call_id}"
        logger.info(f"[{call_id}] Connecting to WebSocket: {ws_url}")

        try:
            ws = await websockets.connect(ws_url)
            self.active_connections[call_id] = ws
            logger.info(f"[{call_id}] WebSocket connected")
            
            # Start background task to listen for messages
            asyncio.create_task(self._listen(call_id, ws))
            return ws
        except Exception as e:
            logger.error(f"[{call_id}] WebSocket connection error: {e}")
            await self._emit('error', call_id, e)
            raise

    async def _listen(self, call_id: str, ws: websockets.WebSocketClientProtocol):
        try:
            async for data in ws:
                try:
                    message = json.loads(data)
                    logger.info(f"[{call_id}] AI message: {message}")
                    await self._emit('message', call_id, message)
                except Exception as e:
                    logger.error(f"[{call_id}] Failed to parse message: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{call_id}] WebSocket closed")
        except Exception as e:
            logger.error(f"[{call_id}] WebSocket listen error: {e}")
            await self._emit('error', call_id, e)
        finally:
            self.active_connections.pop(call_id, None)
            await self._emit('close', call_id)

    async def send_text(self, call_id: str, text: str):
        """Send text message to AI agent."""
        ws = self.active_connections.get(call_id)
        if not ws:
            raise RuntimeError(f"No active WebSocket connection for call {call_id}")
        
        await ws.send(json.dumps({
            "type": "text",
            "text": text
        }))

    async def send_audio(self, call_id: str, audio_data: bytes):
        """Send audio data to AI agent."""
        ws = self.active_connections.get(call_id)
        if not ws:
            raise RuntimeError(f"No active WebSocket connection for call {call_id}")
        
        import base64
        await ws.send(json.dumps({
            "type": "audio",
            "data": base64.b64encode(audio_data).decode('utf-8')
        }))

    async def health_check(self) -> Dict[str, Any]:
        """Check if AI service is healthy."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.service_url}/health")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"AI service health check failed: {e}")
            raise

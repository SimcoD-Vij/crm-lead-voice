# ---------------------------------------------------------
# voice/voice_ai_handler.py
# Voice Call Handler - replaces voice/voice_ai_handler.py
# ---------------------------------------------------------
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Dict

from voice.ai_agent_client import AIAgentClient

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VOICE_AI_HANDLER")

# Initialize AI client
AI_SERVICE_URL = os.getenv('AI_AGENT_SERVICE_URL', 'http://localhost:8001')
ai_client = AIAgentClient(AI_SERVICE_URL)

_CS_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_FILE = _CS_ROOT / 'voice' / 'summary_calls.json'

async def handle_incoming_call_with_ai(call_sid: str, from_number: str, to_number: str, additional_context: dict = None) -> dict:
    """Handle incoming voice call with AI agent integration."""
    additional_context = additional_context or {}
    logger.info(f"[{call_sid}] Handling incoming call from {from_number} with AI agent")

    try:
        # 1. Initialize AI agent for this call
        init_result = await ai_client.initialize_call(call_sid, from_number, {
            "callerName": additional_context.get("callerName", "Customer"),
            "context": {
                "source": additional_context.get("source", "phone"),
                "campaign": additional_context.get("campaign"),
                **additional_context
            }
        })

        logger.info(f"[{call_sid}] AI agent initialized: {init_result}")

        # 2. Connect WebSocket for real-time communication
        await ai_client.connect_websocket(call_sid)

        # 3. Message callbacks are handled within AIAgentClient's _listen loop
        # and emitted via callbacks. For parity, we can attach a default listener here if needed
        # but in this architecture, the call_server or specific handler usually manages the logic.
        
        async def on_message(sid, message):
            if sid != call_sid:
                return
            
            logger.info(f"[{call_sid}] AI message: {message}")
            msg_type = message.get('type')
            
            if msg_type == 'status':
                logger.info(f"[{call_sid}] Status: {message.get('message')}, Node: {message.get('node')}")
            elif msg_type == 'response':
                logger.info(f"[{call_sid}] AI response: {message.get('text')}")
                # In production, send this to TTS and play to caller
            elif msg_type == 'node_transition':
                logger.info(f"[{call_sid}] Transitioned to node: {message.get('node')}")

        ai_client.on('message', on_message)

        async def on_close(sid):
            if sid != call_sid:
                return
            logger.info(f"[{call_sid}] AI WebSocket closed")
            # Final status is often fetched when call ends via end_call_with_ai

        ai_client.on('close', on_close)

        return {
            "success": True,
            "callSid": call_sid,
            "aiInitialized": True
        }

    except Exception as e:
        logger.error(f"[{call_sid}] Failed to initialize AI agent: {e}")
        return {
            "success": False,
            "callSid": call_sid,
            "error": str(e)
        }

async def end_call_with_ai(call_sid: str) -> dict:
    """End call and get AI-gathered context."""
    logger.info(f"[{call_sid}] Ending call with AI agent")

    try:
        result = await ai_client.end_call(call_sid)
        logger.info(f"[{call_sid}] Call ended. Gathered context: {result.get('gathered_context')}")

        # Save call summary
        await save_call_summary(call_sid, result)

        return result
    except Exception as e:
        logger.error(f"[{call_sid}] Failed to end call: {e}")
        raise

async def save_call_summary(call_sid: str, call_data: dict) -> None:
    """Save call summary to JSON file."""
    try:
        # Read existing summaries
        summaries = []
        if SUMMARY_FILE.exists():
            try:
                with open(SUMMARY_FILE, 'r', encoding='utf-8') as f:
                    summaries = json.load(f)
            except Exception:
                pass

        # Add new summary
        summary = {
            "callSid": call_sid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": call_data.get("status"),
            "currentNode": call_data.get("current_node"),
            "gatheredContext": call_data.get("gathered_context", {}),
            "disposition": call_data.get("gathered_context", {}).get("call_disposition", "unknown")
        }

        summaries.append(summary)

        # Save back to file
        with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(summaries, f, indent=2)

        logger.info(f"[{call_sid}] Call summary saved")
    except Exception as e:
        logger.error(f"[{call_sid}] Failed to save call summary: {e}")

async def check_ai_service_health() -> Optional[dict]:
    """Check AI service health."""
    try:
        health = await ai_client.health_check()
        logger.info(f"AI Service Health: {health}")
        return health
    except Exception as e:
        logger.error(f"AI Service is not available: {e}")
        return None

# ---------------------------------------------------------
# ai/sales_bot.py
# Core AI sales agent - replaces agent/salesBot.js
# ---------------------------------------------------------
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from core.config import MODEL, OLLAMA_GENERATE_URL, OLLAMA_URL, TIMEOUT_MS

# ---------------------------------------------------------
# PRODUCT DATA
# ---------------------------------------------------------
PRODUCT_FACTS = {
    "price": "₹1499",
    "benefit": "Extends Li-Ion battery life up to 2x",
    "safety": "Safe-Heat Technology, no overheating, thermal sensors",
    "compat": "Compatible with gaming laptops, smartphones, 6A/12A/16A sockets",
    "description": (
        "XOptimus is a hardware charging adapter. It sits between your charger and the socket. "
        "It stops charging at 80% to protect battery health."
    ),
}

SALES_IDENTITY_PROMPT = """
You are Vijay, a Product Consultant at Hivericks.

CONTEXT:
Live voice call. Speak naturally, like a real human.
Short, calm, conversational responses. Max 2 sentences.

PRODUCT:
XOptimus – a hardware charging adapter (₹1499).
It sits between the charger and socket, stops charging at ~80%,
prevents overcharging, reduces heat, and extends Li-Ion battery life up to 2x.
Compatible with gaming laptops, smartphones, and 6A/12A/16A sockets.

PRIMARY BEHAVIOR:
Start with normal conversation.
Talk about battery health first.
Introduce XOptimus clearly when relevant.
Do not forget to mention the product when explaining solutions.

CONVERSATION LOGIC (IMPORTANT):
- If discussing battery problems → explain the issue first, then clearly say XOptimus solves it.
- If interest is shown → explain what XOptimus is, how it works, and its benefits.
- If asked price → say "It's ₹1499."
- If asked "what is it?" → say it's a hardware adapter that protects battery health.

EXIT & DEFER HANDLING (CRITICAL):
- If user says "later", "busy", or "call later":
  → Acknowledge once
  → Ask: "Would it be okay if I send the product details on WhatsApp?"
  → If yes: confirm, thank them, and END the call
  → Do NOT continue selling

DISINTEREST HANDLING:
- First "not interested" → one gentle check:
  "Understood. Is it mainly the price, or just timing?"
- Second disinterest → thank them and END the call
- Never pitch after repeated disinterest

ABSOLUTE RULES:
- Never loop persuasion
- Never repeat validations
- Never explain product after exit intent
- Never sound scripted or robotic
- No greetings after the first turn
"""


class SalesBrain:
    """
    Per-call/session AI brain.
    Equivalent to the SalesBrain class in agent/salesBot.js
    """

    def __init__(
        self,
        lead_context: dict | None = None,
        memory: dict | None = None,
        mode: str = "VOICE_CALL",
    ):
        self.memory: dict = memory or {}
        self.history: list[dict] = self.memory.get("history", [])
        if not isinstance(self.history, list):
            self.history = []
        self.lead_context: dict = lead_context or {}
        self.is_start: bool = len(self.history) == 0

    async def process_turn(self, user_message: str) -> dict[str, Any]:
        """
        Main conversation handler.
        Returns {'response': str, 'stageId': int, 'memory': dict}
        """
        last_assistant_msgs = [h for h in self.history if h.get("role") == "assistant"]
        last_assistant_text = last_assistant_msgs[-1].get("text", "") if last_assistant_msgs else ""
        context = "\n".join(
            f"{h['role']}: {h['text']}" for h in self.history[-6:]
        )

        summary_context = ""
        if self.lead_context and self.lead_context.get("summary"):
            summary_context = f"PREVIOUS CONVERSATION SUMMARY:\n{self.lead_context['summary']}\n"

        # --------------------------------------------------
        # 1. HARD TEMPLATE OVERRIDES (100% reliable exits)
        # --------------------------------------------------
        hard_response: str | None = None
        msg_lower = user_message.lower()

        if re.search(r"busy|later|meeting|call back", user_message, re.I):
            hard_response = (
                "I understand. I'll send the details over WhatsApp now. "
                "Is there anything else I can help with, or should we hang up?"
            )
        elif (
            re.search(r"yes|okay|sure|go ahead", user_message, re.I)
            and re.search(r"whatsapp|detail", last_assistant_text, re.I)
        ):
            hard_response = (
                "Great! I'll send those details right away. "
                "Before I go, is there anything else you'd like to discuss?"
            )
        elif (
            re.search(r"no|nothing|that is all|that's it|bye", user_message, re.I)
            and re.search(r"anything else|help with|whatsapp|detail", last_assistant_text, re.I)
        ):
            hard_response = "Thank you for your time! Have a great day. [HANGUP]"

        if hard_response:
            self.history.append({"role": "user", "text": user_message})
            self.history.append({"role": "assistant", "text": hard_response})
            self.memory["history"] = self.history
            return {"response": hard_response, "stageId": 2, "memory": self.memory}

        # --------------------------------------------------
        # 2. INTENT OVERRIDES for LLM
        # --------------------------------------------------
        override = ""
        if re.search(r"whatsapp|send.*details|text me", user_message, re.I):
            override = f"CRITICAL: Agree to send details on WhatsApp. ASK: \"I'd be happy to send you the details on WhatsApp, would that work?\""
        elif re.search(r"price|cost|how much", user_message, re.I):
            override = f"CRITICAL: The Price is {PRODUCT_FACTS['price']}. Answer ONLY the price."
        elif re.search(r"what.*do|function|work|what is", user_message, re.I):
            override = "CRITICAL: Explain it is a hardware adapter that prevents overcharging."
        elif re.search(r"heat|safety|cool|safe|fire|burn", user_message, re.I):
            override = "CRITICAL: Mention Safe-Heat Technology and thermal sensors. It is 100% safe."
        elif re.search(r"laptop|gaming|high end|heavy", user_message, re.I):
            override = "CRITICAL: Confirm it works with high-end gaming laptops and all sockets (6A/12A/16A)."

        # --------------------------------------------------
        # 3. BUILD PROMPT
        # --------------------------------------------------
        if override:
            prompt = f"{override}\n\n{summary_context}\nCONVERSATION SO FAR:\n{context}\nUser: {user_message}\n\nVijay:"
        else:
            prompt = f"""
{SALES_IDENTITY_PROMPT}

{summary_context}

PRODUCT DATASHEET:
- Description: {PRODUCT_FACTS['description']}
- Price: {PRODUCT_FACTS['price']}
- Benefit: {PRODUCT_FACTS['benefit']}
- Compatibility: {PRODUCT_FACTS['compat']}
- Safety: {PRODUCT_FACTS['safety']}

CONVERSATION SO FAR:
{context}
User: {user_message}

INSTRUCTION:
Respond as Vijay.
- ANSWER THE USER'S QUESTION DIRECTLY IN THE FIRST SENTENCE.
- DO NOT give a general battery health lecture.
- Max 15 words.

Vijay:"""

        payload: dict[str, Any] = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "stop": ["User:", "\n", "Vijay:"],
                "num_predict": 35,
                "repeat_penalty": 1.6,
            },
        }

        try:
            timeout_s = TIMEOUT_MS / 1000
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                res = await client.post(OLLAMA_GENERATE_URL, json=payload)
                res.raise_for_status()

            content: str = (res.json().get("response") or "").strip()
            content = re.sub(r"Vijay:|User:|Assistant:", "", content, flags=re.I).strip()
            content = re.sub(r"^[,. ]+", "", content).strip()
            content = content.strip("\"'")

            if not content:
                content = "Could you tell me more about your device usage?"

            self.history.append({"role": "user", "text": user_message})
            self.history.append({"role": "assistant", "text": content})
            self.memory["history"] = self.history

            return {"response": content, "stageId": 2, "memory": self.memory}

        except Exception:
            return {"response": "I didn't quite catch that.", "stageId": 2, "memory": self.memory}

    async def determine_stage(self, user_message: str) -> int:
        """Deprecated – kept for interface compatibility."""
        return 2


# ---------------------------------------------------------
# MODULE-LEVEL FUNCTIONS
# ---------------------------------------------------------

async def generate_response(params: dict) -> dict[str, Any]:
    """Top-level wrapper - compatible with sms_engine and email_engine callers."""
    brain = SalesBrain(
        lead_context=params.get("leadContext", {}),
        memory=params.get("memory", {}),
        mode=params.get("mode", "VOICE_CALL"),
    )
    return await brain.process_turn(params.get("userMessage", ""))


async def warmup() -> None:
    """No-op warmup (MCP replaced). Kept for API compatibility."""
    pass


async def generate_structured_summary(history: list | str) -> dict[str, Any]:
    """
    Heuristic summary from conversation history.
    Equivalent to generateStructuredSummary() in salesBot.js
    """
    if isinstance(history, (list, dict)):
        txt = json.dumps(history).lower()
    else:
        txt = str(history).lower()

    asked_price = any(k in txt for k in ["price", "cost", "much"])
    asked_details = any(k in txt for k in ["what", "how", "details"])
    said_later = any(k in txt for k in ["later", "busy", "call back"])
    agreed_whatsapp = any(k in txt for k in ["whatsapp", "send", "yes"])

    interest = "medium"
    if said_later:
        interest = "callback"
    if asked_price and agreed_whatsapp:
        interest = "high"

    return {
        "interest_level": interest,
        "key_topics": [k for k, cond in [("price", asked_price), ("details", asked_details)] if cond],
        "next_action": "schedule_callback" if said_later else "send_whatsapp",
        "conversation_summary": "User engaged in product inquiry.",
        "user_intent": "callback" if said_later else "inquiry",
    }


async def generate_text_summary(history: list | str) -> str:
    """
    AI-generated one-sentence text summary.
    Equivalent to generateTextSummary() in salesBot.js
    """
    try:
        content = json.dumps(history) if not isinstance(history, str) else history
        prompt = f'Summarize this sales call transcript in 1 sentence. Start with "User was...":\n{content}'
        payload = {"model": MODEL, "prompt": prompt, "stream": False}

        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(OLLAMA_GENERATE_URL, json=payload)
            return (res.json().get("response") or "").strip() or "User involved in discussion."
    except Exception as e:
        print(f"⚠️ AI Summary Failed (Ollama offline): {e}")
        return "User was contacted for a sales follow-up regarding XOptimus battery health."


async def generate_final_summary(history: list) -> dict[str, Any]:
    """
    Cross-event final summary.
    Equivalent to generateFinalSummary() in salesBot.js
    """
    try:
        structured = await generate_structured_summary(history)
        if structured["interest_level"] == "callback":
            status = "CALL_CALLBACK"
        elif structured["interest_level"] == "high":
            status = "CALL_INTERESTED"
        else:
            status = "CALL_COMPLETED"
        return {"lead_status": status, "analysis": structured}
    except Exception:
        return {
            "lead_status": "CALL_COMPLETED",
            "analysis": {"interest_level": "medium", "next_action": "send_whatsapp"},
        }


async def generate_feedback_request(
    summary: Any,
    mode: str,
    name: str,
    attempt_count: int = 0,
    memory: dict | None = None,
) -> str:
    """
    Generates a post-call WhatsApp or Email follow-up message.
    Equivalent to generateFeedbackRequest() in salesBot.js
    """
    try:
        summary_str = json.dumps(summary)
        is_callback = bool(re.search(r"callback|busy|later", summary_str, re.I))

        if is_callback:
            prompt = (
                f"Write a short, polite WhatsApp message to {name}.\n"
                f"Context: The user was busy or asked for a callback.\n"
                f"Summary: {summary_str}\n"
                f"Product: XOptimus (₹1499).\nLink: hivericks.com/xoptimus.\n\n"
                f'Say: "Hi {name}, as discussed, I\'ll share the XOptimus battery saver details here. '
                f'Let me know when you\'re free to chat!" (Sign off: Vijay)'
            )
        else:
            channel_word = "Email" if mode == "EMAIL" else "WhatsApp"
            prompt = (
                f"Write a professional {channel_word} message to {name}.\n"
                f"Context: Follow-up after a call.\n"
                f"Call Summary: {summary_str}\n"
                f"Product: XOptimus (₹1499, extends battery life).\n"
                f"Goal: Nudge them to buy or learn more.\nLink: hivericks.com/xoptimus.\n\n"
                f"Keep it short and friendly. (Sign off: Vijay)"
            )

        payload = {"model": MODEL, "prompt": prompt, "stream": False}
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(OLLAMA_GENERATE_URL, json=payload)
            result = res.json().get("response") or ""
            return result if result else _get_default_feedback(mode, name, is_callback)
    except Exception as e:
        print(f"⚠️ AI Feedback Generation Failed (Ollama offline): {e}")
        summary_str = json.dumps(summary)
        is_callback = bool(re.search(r"callback|busy|later", summary_str, re.I))
        return _get_default_feedback(mode, name, is_callback)


def _get_default_feedback(mode: str, name: str, is_callback: bool) -> str:
    if is_callback:
        return (
            f"Hi {name}, as discussed, I'll share the XOptimus battery saver details here. "
            f"Let me know when you're free to chat! - Vijay, Hivericks"
        )
    if mode == "EMAIL":
        return (
            f"Subject: Follow up from Hivericks\n\n"
            f"Hi {name},\n\nIt was great speaking with you. As promised, here are the details for "
            f"XOptimus (hivericks.com/xoptimus), our battery health protector. It extends your "
            f"device's battery life up to 2x for just ₹1499.\n\nBest regards,\nVijay"
        )
    return (
        f"Hi {name}, thanks for your time today! Here are the details for XOptimus: "
        f"hivericks.com/xoptimus. Let me know if you have any questions! - Vijay"
    )


async def generate_opening(lead: dict) -> str:
    """Returns the call opening greeting."""
    return f"Hi {lead.get('name', 'there')}, this is Vijay from Hivericks calling regarding a quick battery health update. Is this a good time?"


def detect_intent(message: str) -> dict[str, str]:
    """Basic intent detector – kept for API compatibility."""
    return {"type": "GENERAL"}

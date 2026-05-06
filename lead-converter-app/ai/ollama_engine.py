# ---------------------------------------------------------
# ai/ollama_engine.py
# Ollama HTTP wrapper - replaces ai/ollama_engine.js
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from core.config import MODEL, OLLAMA_URL, TIMEOUT_MS

# ---------------------------------------------------------
# 1. HARDCODED KNOWLEDGE BASE
# ---------------------------------------------------------
PRODUCT_FACTS = """
PRODUCT: XOptimus Smart Charger (Wall Adapter)
MANUFACTURER: Hivericks Technologies Pvt Ltd (Chennai).

CORE VALUE PROPOSITION:
- Increases Li-Ion battery life expectancy.
- Prevents overcharging/heating using real-time monitoring.
- Saves energy by maintaining optimal charge levels.

KEY MODES:
1. Smart Mode (Default): Optimizes for daily battery health.
2. Gaming Mode: High-end mode for heavy usage/high discharge.
3. Full Charge Mode: Forces 100% charge when needed.

SPECS:
- Input/Output: 110-230V AC.
- Max Current: 5A.
- Connectivity: Bluetooth 5.0 (BLE).
- App: "Xoptimus" (Play Store).
"""

# ---------------------------------------------------------
# 2. SALES PROTOCOLS
# ---------------------------------------------------------
SALES_PROTOCOL = """
OBJECTION HANDLING PROTOCOL:
If user says "No budget", "Not interested", or "Things are fine":
1. ACKNOWLEDGE & PIVOT (Pattern Interrupt):
   - "Totally fair. Most people feel that way until the battery dies."
2. FORCED CHOICE (Truth Detector):
   - "Is it that you've evaluated alternatives and found them lacking, or just haven't had time to look?"
3. EXIT WITH VALUE:
   - "Would it be helpful to see the upside math? If not, we walk. Fair?"
"""

# ---------------------------------------------------------
# 3. SYSTEM PERSONAS
# ---------------------------------------------------------
SYSTEM_PROMPTS: dict[str, str] = {
    "CONSULTATIVE": """
    You are Vijay, Senior Consultant at Hivericks Technologies.
    Role: Consultative Sales Expert for XOptimus.

    GUIDELINES:
    - Do NOT invent specs. Use PRODUCT_KNOWLEDGE only.
    - Keep answers concise (Max 2 sentences).
    - Ask exactly ONE clarifying question per turn.
    - NO FLUFF: Don't say "I hope you are well."
    """,
    "GHOST": """
    You are Vijay. The user has stopped replying.
    Role: Re-engagement specialist.
    Style: Blunt, casual, "Chris Voss" style.
    - "Have you given up on fixing your battery issues?"
    - "Did you get abducted by aliens?"
    """,
}


async def generate_response(
    user_message: str,
    mode: str = "CONSULTATIVE",
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Generates an AI response using XML-structured prompting via Ollama /api/chat.
    Equivalent to generateResponse() in ai/ollama_engine.js
    """
    if history is None:
        history = []

    try:
        print(f"   🧠 AI Thinking ({mode} Mode)...")
        base_persona = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["CONSULTATIVE"])

        structured_system = f"""
<SYSTEM>
{base_persona}
</SYSTEM>

<PRODUCT_KNOWLEDGE>
{PRODUCT_FACTS}
</PRODUCT_KNOWLEDGE>

<SALES_PROTOCOL>
{SALES_PROTOCOL}
</SALES_PROTOCOL>

<INSTRUCTION>
Answer the user based on the knowledge above.
If they object, follow the SALES_PROTOCOL.
Keep it short.
</INSTRUCTION>
"""

        messages: list[dict[str, str]] = [
            {"role": "system", "content": structured_system},
            *history,
            {"role": "user", "content": user_message},
        ]

        payload: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_ctx": 4096},
        }

        timeout_s = TIMEOUT_MS / 1000
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()

        reply: str = response.json()["message"]["content"].strip()
        print(f'   💡 AI Answer: "{reply}"')
        return reply

    except httpx.TimeoutException:
        print("   ❌ Ollama Error: Timeout")
        return "I'm having a little trouble connecting. Can you repeat that?"
    except Exception as e:
        print(f"   ❌ Ollama Error: {e}")
        return "Let me double-check that with my technical team. One moment."

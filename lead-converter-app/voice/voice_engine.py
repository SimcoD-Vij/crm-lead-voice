# ---------------------------------------------------------
# voice/voice_engine.py
# Twilio call initiator - replaces voice/voice_engine.js
# ---------------------------------------------------------
from __future__ import annotations

import os

from twilio.rest import Client as TwilioClient

from core.config import TWILIO_AUTH, TWILIO_PHONE, TWILIO_SID

_twilio_client: TwilioClient | None = None


def _get_client() -> TwilioClient:
    global _twilio_client
    if _twilio_client is None:
        _twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
    return _twilio_client


async def dial_lead(
    lead: dict,
    opening_file: str | None = None,
    opening_text: str | None = None,
) -> str | None:
    """
    Initiates a Twilio voice call to a lead.
    Equivalent to dialLead() in voice/voice_engine.js

    Returns the Call SID on success, None on failure.
    """
    # Always read SERVER_URL fresh (may be updated dynamically)
    server_url = os.environ.get("SERVER_URL", "")
    if not server_url:
        raise RuntimeError("Missing SERVER_URL in environment - Is Ngrok running?")

    phone = lead.get("phone")
    if not phone:
        print(f"      ⚠️ Skipping Call: Lead {lead.get('name')} has no phone number.")
        return None

    print(f"\n☎️ INITIATING CALL to {lead.get('name')} ({phone})...")
    print(f"      🔗 Webhook Server: {server_url}")

    # Build call URL with opening params
    call_url = f"{server_url}/voice?"
    if opening_file:
        from urllib.parse import quote
        call_url += f"openingFile={quote(opening_file)}&"
    if opening_text:
        from urllib.parse import quote
        call_url += f"openingText={quote(opening_text)}&"

    try:
        client = _get_client()
        call = client.calls.create(
            url=call_url,
            to=phone,
            from_=TWILIO_PHONE,
            status_callback=f"{server_url}/voice/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        print(f"      ✅ Call Initiated! SID: {call.sid}")
        return call.sid
    except Exception as error:
        print(f"      ❌ VoiceEngine Error: {error}")
        raise

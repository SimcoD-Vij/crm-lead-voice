# ---------------------------------------------------------
# voice/call_server.py
# Inbound/Outbound Voice Server (Port 3000) - replaces voice/call_server.js
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse

from ai.sales_bot import generate_response, generate_final_summary
from ai.voice_utils import text_to_ssml
from core.config import (
    CALL_LOGS_FILE,
    EVENTS_FILE,
    LEADS_FILE,
    SUMMARY_CALLS_FILE,
    TWILIO_PHONE,
    USE_DOGRAH_AI,
    VOICE_CONVO_DIR,
)
from core.file_io import read_json, write_json

app = Flask(__name__)
# Suppress Werkzeug logs to stay clean
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

PORT = 3000
PENDING_LLM_REQUESTS: dict[str, str] = {}


def _get_server_url() -> str:
    return os.environ.get("SERVER_URL", f"http://localhost:{PORT}")


def _get_lead_context(phone: str) -> dict:
    """Helper to find lead and return basic context."""
    leads = read_json(LEADS_FILE, fallback=[])
    clean = phone.replace("+", "")
    lead = next((l for l in leads if l.get("phone") in (phone, clean)), None)
    if not lead:
        return {"name": "Customer", "summary": "", "score": 0}

    summary_text = ""
    s = lead.get("last_call_summary")
    if s:
        if isinstance(s, dict):
            summary_text = s.get("text_summary") or s.get("analysis", {}).get("conversation_summary", "")
        else:
            summary_text = str(s)

    return {
        "name": (lead.get("name") or "Customer").split()[0],
        "summary": summary_text,
        "score": lead.get("score", 0),
    }


def _update_lead_status(
    phone: str, status: str, summary: dict | None = None, attempt_inc: int = 0
) -> None:
    leads = read_json(LEADS_FILE, fallback=[])
    clean = phone.replace("+", "")
    lead = next((l for l in leads if l.get("phone") in (phone, clean)), None)

    if not lead:
        lead = {
            "phone": clean,
            "name": "Incoming Caller",
            "email": "",
            "status": status,
            "score": 10,
            "attempt_count": 0,
            "next_action_due": datetime.now().date().isoformat(),
            "source": "INBOUND_CALL",
        }
        leads.append(lead)
    else:
        lead["status"] = status
        lead["attempt_count"] = (lead.get("attempt_count") or 0) + attempt_inc

    try:
        from scoring.scoring_engine import calculate_score
        intent = "WARM"
        if summary and summary.get("analysis"):
            intent = summary["analysis"].get("interest_level", "WARM")
        score_data = calculate_score(lead, intent.upper(), lead["status"])
        lead["score"] = score_data["score"]
        lead["category"] = score_data["category"]
    except Exception:
        pass

    if summary:
        lead["last_call_summary"] = json.dumps(summary)

    write_json(LEADS_FILE, leads)


def _log_turn(sid: str, role: str, text: str) -> None:
    """Logs a single turn to the voice convo file for this call."""
    VOICE_CONVO_DIR.mkdir(parents=True, exist_ok=True)
    fpath = VOICE_CONVO_DIR / f"{sid}.json"
    convo = read_json(fpath, fallback=[])
    convo.append({"role": role, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()})
    write_json(fpath, convo)


def _get_filler_text(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ["price", "cost", "how much"]):
        return "Let me check the pricing for you..."
    if any(k in lower for k in ["detail", "work", "what is"]):
        return "Sure, let me pull up those details..."
    return "Give me just one second..."


def _process_call_completion_sync(sid: str, phone: str, convo: list, ts: str | None = None) -> None:
    """Synchronous wrapper for async processing so Flask can dispatch it in background."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.create_task(_process_call_completion(sid, phone, convo, ts))


async def _process_call_completion(sid: str, phone: str, convo: list, ts: str | None = None) -> None:
    print(f"\n   🧾 PROCESSING COMPLETED CALL FOR {phone} [SID: {sid}]")
    if not convo:
        print("      ⚠️ No recorded conversation (Ghost call?). Skipping summary.")
        _update_lead_status(phone, "CALL_NO_ANSWER", None, 1)
        return

    txt = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in convo)
    summary_data = await generate_final_summary(convo)

    _update_lead_status(phone, summary_data.get("lead_status", "CALL_COMPLETED"), summary_data, 1)

    s_calls = read_json(SUMMARY_CALLS_FILE, fallback=[])
    s_calls.append({
        "call_sid": sid,
        "phone": phone,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "summary": summary_data,
        "transcript": convo,
    })
    write_json(SUMMARY_CALLS_FILE, s_calls)

    events = read_json(EVENTS_FILE, fallback=[])
    events.append({
        "event_id": f"evt_voice_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "lead_id": phone,
        "channel": "VOICE",
        "type": "CALL_COMPLETED",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "summary": summary_data.get("analysis", {}),
        "master_summary": summary_data.get("analysis", {}).get("conversation_summary", ""),
    })
    write_json(EVENTS_FILE, events)

    print(f"      ✅ Summary specific to Call SID '{sid}' successfully saved!")


# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@app.route("/voice", methods=["POST", "GET"])
def voice_entry() -> Response:
    """Initial webhook from Twilio."""
    server_url = _get_server_url()
    sid = request.values.get("CallSid", "")
    from_num = request.values.get("From", "")
    to_num = request.values.get("To", "")

    opening_file = request.values.get("openingFile")
    opening_text = request.values.get("openingText")

    if from_num == TWILIO_PHONE:
        phone = to_num
        print(f"\n📞 OUTBOUND CALL ANSWERED: {phone}")
    else:
        phone = from_num
        print(f"\n📞 INBOUND CALL RECEIVED: {phone}")
        # Send to orchestrator logic via dograh or native?
        # Standard native logic handles inbound by default if no override

    if USE_DOGRAH_AI:
        print("      🐶 Dograh AI Mode ON. Keeping call alive for hand-off...")
        vr = VoiceResponse()
        vr.say("Please hold while we connect you to our AI agent. This may take up to a minute. Do not hang up.")
        vr.pause(length=20)
        vr.say("Still connecting... thank you for your patience.")
        vr.pause(length=20)
        # Redirect to same endpoint to loop hold message if Dograh hasn't taken over
        vr.redirect(f"{server_url}/voice")
        return Response(str(vr), mimetype="text/xml")

    lead_ctx = _get_lead_context(phone)
    greeting = opening_text or f"Hi {lead_ctx['name']}, this is Vijay from Hivericks. Am I catching you at a bad time?"

    _log_turn(sid, "assistant", greeting)

    vr = VoiceResponse()
    if opening_file:
        vr.play(opening_file)
    else:
        vr.say(greeting, voice="Polly.Matthew-Neural")

    gather = vr.gather(input="speech", action=f"{server_url}/voice/input", speech_timeout="auto")
    return Response(str(vr), mimetype="text/xml")


@app.route("/voice/input", methods=["POST", "GET"])
def voice_input() -> Response:
    """User speech received from Twilio Gather."""
    server_url = _get_server_url()
    sid = request.values.get("CallSid", "")
    phone = request.values.get("To", "") if request.values.get("From", "") == TWILIO_PHONE else request.values.get("From", "")
    speech = request.values.get("SpeechResult", "").strip()

    if not speech:
        vr = VoiceResponse()
        vr.say("I didn't quite catch that. Could you say it again?", voice="Polly.Matthew-Neural")
        vr.gather(input="speech", action=f"{server_url}/voice/input", speech_timeout="auto")
        return Response(str(vr), mimetype="text/xml")

    print(f'   🗣️ User ({phone}): "{speech}"')
    _log_turn(sid, "user", speech)

    convo = read_json(VOICE_CONVO_DIR / f"{sid}.json", fallback=[])
    ctx = _get_lead_context(phone)

    # Trigger LLM in background
    async def fetch_llm() -> None:
        try:
            res = await generate_response({
                "userMessage": speech,
                "mode": "VOICE_CALL",
                "leadContext": ctx,
                "memory": {"history": convo},
            })
            ans = res.get("response", "") if isinstance(res, dict) else str(res)
            PENDING_LLM_REQUESTS[sid] = ans
        except Exception as e:
            print(f"      ❌ LLM Background Failed: {e}")
            PENDING_LLM_REQUESTS[sid] = "I'm having a little trouble connecting. Can you repeat that?"

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.create_task(fetch_llm())

    filler = _get_filler_text(speech)
    vr = VoiceResponse()
    vr.say(filler, voice="Polly.Matthew-Neural")
    vr.redirect(f"{server_url}/voice/deferred-response")
    return Response(str(vr), mimetype="text/xml")


@app.route("/voice/deferred-response", methods=["POST", "GET"])
def deferred_response() -> Response:
    """Twilio hits this after playing the filler."""
    server_url = _get_server_url()
    sid = request.values.get("CallSid", "")
    ans = PENDING_LLM_REQUESTS.pop(sid, "I'm sorry, I missed that. Are you still there?")

    vr = VoiceResponse()
    if "[HANGUP]" in ans:
        clean = ans.replace("[HANGUP]", "").strip()
        _log_turn(sid, "assistant", f"{clean} (HANGING UP)")
        if clean:
            vr.say(clean, voice="Polly.Matthew-Neural")
        vr.hangup()
    else:
        _log_turn(sid, "assistant", ans)
        if USE_DOGRAH_AI:
            # Twilio Polly
            vr.say(ans, voice="Polly.Matthew-Neural")
        else:
            # Also Twilio Polly (fallback was XTTS in JS, but it was commented out)
            vr.say(ans, voice="Polly.Matthew-Neural")
        vr.gather(input="speech", action=f"{server_url}/voice/input", speech_timeout="auto")

    return Response(str(vr), mimetype="text/xml")


@app.route("/voice/status", methods=["POST", "GET"])
def voice_status() -> Response:
    """Call status updates (completed, busy, etc)."""
    sid = request.values.get("CallSid", "")
    status = request.values.get("CallStatus", "")
    phone = request.values.get("To", "") if request.values.get("From", "") == TWILIO_PHONE else request.values.get("From", "")
    duration = request.values.get("CallDuration", "0")

    print(f"\nℹ️ Call {sid} to {phone} Status Updated: {status}")

    logs = read_json(CALL_LOGS_FILE, fallback=[])
    logs.append({
        "sid": sid,
        "phone": phone,
        "status": status,
        "duration": duration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    write_json(CALL_LOGS_FILE, logs)

    if status in ("completed", "failed", "busy", "no-answer", "canceled"):
        if status == "completed":
            convo = read_json(VOICE_CONVO_DIR / f"{sid}.json", fallback=[])
            _process_call_completion_sync(sid, phone, convo)
        else:
            stat_map = {"busy": "CALL_BUSY", "no-answer": "CALL_NO_ANSWER", "failed": "CALL_FAILED"}
            _update_lead_status(phone, stat_map.get(status, "CALL_IDLE"), None, 1)

    return Response("OK", status=200)


if __name__ == "__main__":
    print(f"\n📞 INTERNAL VOICE SERVER RUNNING ON PORT {PORT}")
    app.run(host="0.0.0.0", port=PORT)

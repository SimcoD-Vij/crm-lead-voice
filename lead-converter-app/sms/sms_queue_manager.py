# ---------------------------------------------------------
# sms/sms_queue_manager.py
# Inbound SMS queue + session management - replaces sms/sms_queue_manager.js
# ---------------------------------------------------------
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from twilio.rest import Client as TwilioClient

from ai.memory import get_memory, upsert_memory
from ai.sales_bot import generate_response, generate_structured_summary, generate_final_summary
from core.config import (
    ACTIVE_WINDOWS_FILE,
    EVENTS_FILE,
    LEADS_FILE,
    SMS_HISTORY_FILE,
    SMS_QUEUE_FILE,
    TWILIO_AUTH,
    TWILIO_SID,
    TWILIO_WHATSAPP_FROM,
)
from core.file_io import read_json, write_json
from sms.sms_engine import log_sms_session

_twilio_client: TwilioClient | None = None


def _get_client() -> TwilioClient:
    global _twilio_client
    if _twilio_client is None:
        _twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
    return _twilio_client


def _update_lead_status(phone: str, status: str) -> None:
    """
    Updates or creates a lead's status.
    Equivalent to updateLeadStatus() in sms_queue_manager.js
    """
    try:
        leads: list[dict] = read_json(LEADS_FILE, fallback=[])
        clean_id = phone.replace("whatsapp:", "")
        lead = next((l for l in leads if l.get("phone") in (phone, clean_id)), None)

        if not lead:
            print(f"      ✨ Creating New Lead for {phone}")
            now_str = datetime.now(timezone.utc).isoformat()
            lead = {
                "phone": clean_id,
                "name": "New Website Lead",
                "email": "",
                "status": status or "SMS_ENGAGED",
                "score": 10,
                "attempt_count": 1,
                "next_action_due": datetime.now().date().isoformat(),
                "last_interaction": now_str,
                "source": "INBOUND_SMS",
            }
            leads.append(lead)
        else:
            skip_statuses = {"SMS_TO_CALL_REQUESTED", "SMS_CALL_SCHEDULED"}
            if lead.get("status") not in skip_statuses:
                lead["status"] = status or lead["status"]

        write_json(LEADS_FILE, leads)
    except Exception as e:
        print(f"CRITICAL ERROR UPDATING LEAD: {e}")


async def handle_inbound_message(lead_id: str, user_message: str) -> None:
    """
    Processes a single inbound SMS message and sends an AI reply.
    Equivalent to handleInboundMessage() in sms_queue_manager.js
    """
    _update_lead_status(lead_id, "SMS_RECEIVED")
    log_sms_session(lead_id, "user", user_message)

    # Manage conversation window
    windows: dict = {}
    if ACTIVE_WINDOWS_FILE.exists():
        try:
            windows = json.loads(ACTIVE_WINDOWS_FILE.read_text(encoding="utf-8"))
        except Exception:
            windows = {}

    window = windows.get(lead_id)
    if not window:
        print(f"      🆕 New Conversation Window for {lead_id}")
        window = {
            "start_time": datetime.now(timezone.utc).isoformat(),
            "last_interaction": datetime.now(timezone.utc).isoformat(),
            "lead_id": lead_id,
        }
        leads: list[dict] = read_json(LEADS_FILE, fallback=[])
        clean_id = lead_id.replace("whatsapp:", "")
        lead = next((l for l in leads if l.get("phone") in (lead_id, clean_id)), None)
        if lead and lead.get("last_call_summary"):
            print(f"      🧠 Loaded Context from previous interaction")
    else:
        print("      🔄 Resuming Active Window...")
        window["last_interaction"] = datetime.now(timezone.utc).isoformat()

    windows[lead_id] = window
    ACTIVE_WINDOWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_WINDOWS_FILE.write_text(json.dumps(windows, indent=2), encoding="utf-8")

    # Generate AI reply
    memory = await get_memory(lead_id)
    ai_result = await generate_response({
        "userMessage": user_message,
        "memory": memory,
        "mode": "SMS_CHAT",
    })
    final_response: str = ai_result.get("response", "") if isinstance(ai_result, dict) else str(ai_result)

    # Safety filter
    bad_phrases = ["cannot create content", "illegal", "promote", "harmful"]
    if any(p in final_response.lower() for p in bad_phrases):
        print("   🛡️ SAFETY FILTER: Caught LLM Refusal.")
        final_response = (
            "That sounds important. To ensure I understand fully and give you the best details, "
            "could we discuss this on a quick call?"
        )

    # Update score
    _update_lead_status(lead_id, "SMS_ENGAGED")
    try:
        from scoring.scoring_engine import calculate_score
        leads = read_json(LEADS_FILE, fallback=[])
        clean_id = lead_id.replace("whatsapp:", "")
        idx = next((i for i, l in enumerate(leads) if l.get("phone") in (lead_id, clean_id)), None)
        if idx is not None:
            score_result = calculate_score(leads[idx], "WARM", leads[idx].get("status", ""))
            leads[idx]["score"] = score_result["score"]
            leads[idx]["category"] = score_result["category"]
            print(f"      💯 Score Updated: {score_result['score']} ({score_result['category']})")
            write_json(LEADS_FILE, leads)

            try:
                from crm.crm_connector import push_interaction_to_stream
                await push_interaction_to_stream(leads[idx], "whatsapp", {
                    "summary": f"WhatsApp Inbound: {user_message[:50]}...",
                    "intent": "engaged",
                    "transcription": user_message,
                    "nextPrompt": final_response,
                })
            except Exception:
                pass
    except Exception:
        pass

    # Send reply via Twilio
    from_num = TWILIO_WHATSAPP_FROM
    to_num = lead_id if lead_id.startswith("whatsapp:") else f"whatsapp:{lead_id}"
    client = _get_client()
    client.messages.create(body=final_response, from_=from_num, to=to_num)

    log_sms_session(lead_id, "assistant", final_response)
    await upsert_memory(lead_id, {"last_bot_message": final_response})

    # Escalation checks
    lower = user_message.lower()
    if "call me" in lower and ("now" in lower or "ready" in lower):
        _update_lead_status(lead_id, "SMS_TO_CALL_REQUESTED")
        print("      🚨 Escalation (Immediate) Triggered!")
    elif any(k in lower for k in ["schedule", "tomorrow", "time", "discuss", "clarif"]):
        _update_lead_status(lead_id, "SMS_CALL_SCHEDULED")
        print("      📅 Scheduling/Clarification Triggered!")


async def process_inbound_queue() -> int:
    """
    Drains the inbound SMS queue file and processes each message.
    Equivalent to processInboundQueue() in sms_queue_manager.js
    """
    print("DEBUG: Checking Queue...")
    queue: list[dict] = read_json(SMS_QUEUE_FILE, fallback=[])
    if not queue:
        return 0

    print(f"\n📨 QUEUE MANAGER: Processing {len(queue)} inbound messages...")
    processed_count = 0

    while queue:
        item = queue.pop(0)
        lead_id = item.get("lead_id", "")
        message = item.get("message", "")
        print(f'   👉 Processing: {lead_id} ("{message}")')
        try:
            await handle_inbound_message(lead_id, message)
            processed_count += 1
        except Exception as e:
            print(f"      ❌ Error processing {lead_id}: {e}")

    write_json(SMS_QUEUE_FILE, [])
    return processed_count


async def finalize_sms_sessions() -> None:
    """
    Summarizes stale SMS sessions (>12h idle).
    Equivalent to finalizeSmsSessions() in sms_queue_manager.js
    """
    print("   🧹 SMS MAINTENANCE: Checking for stale sessions...")
    if not SMS_HISTORY_FILE.exists():
        return

    try:
        history: dict = json.loads(SMS_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    now = datetime.now(timezone.utc)
    TIMEOUT_HOURS = 12
    leads_updated = False
    leads: list[dict] = read_json(LEADS_FILE, fallback=[])

    for lead_id, session in history.items():
        if session.get("summarized"):
            continue

        last_ts = session.get("last_interaction") or session.get("session_start")
        if not last_ts:
            continue
        try:
            from datetime import datetime as dt
            last_time = dt.fromisoformat(last_ts.replace("Z", "+00:00"))
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            diff_hours = (now - last_time).total_seconds() / 3600
        except Exception:
            continue

        if diff_hours >= TIMEOUT_HOURS:
            print(f"      Finalizing SMS Session for {lead_id} ({diff_hours:.1f}h idle)")
            messages = session.get("messages", [])
            transcript_text = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in messages
            )

            try:
                summary_data = await generate_structured_summary(transcript_text)

                events: list[dict] = read_json(EVENTS_FILE, fallback=[])
                events.append({
                    "event_id": f"evt_sms_{int(now.timestamp() * 1000)}",
                    "lead_id": lead_id,
                    "channel": "WHATSAPP",
                    "type": "SMS_SESSION_COMPLETE",
                    "timestamp": now.isoformat(),
                    "summary": summary_data,
                    "master_summary": summary_data.get("conversation_summary"),
                })
                write_json(EVENTS_FILE, events)

                clean_id = lead_id.replace("whatsapp:", "")
                lead = next((l for l in leads if l.get("phone") in (lead_id, clean_id)), None)
                if lead:
                    try:
                        from crm.crm_connector import push_interaction_to_stream
                        await push_interaction_to_stream(lead, "whatsapp", {
                            "summary": summary_data.get("conversation_summary"),
                            "intent": summary_data.get("user_intent"),
                            "transcription": f"SMS Thread Finalized. Transcript: {transcript_text[:500]}...",
                            "nextPrompt": summary_data.get("next_action"),
                        })
                    except Exception:
                        pass

                    lead_events = [e for e in events if e.get("lead_id") == lead_id]
                    final_summary = await generate_final_summary(
                        [{"date": e.get("timestamp"), "summary": e.get("summary")} for e in lead_events]
                    )
                    lead["last_call_summary"] = json.dumps(final_summary)
                    leads_updated = True

                session["summarized"] = True
                session["summary"] = summary_data
            except Exception as err:
                print(f"      ❌ SMS Summary Failed for {lead_id}: {err}")

    if leads_updated:
        write_json(LEADS_FILE, leads)
    SMS_HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")

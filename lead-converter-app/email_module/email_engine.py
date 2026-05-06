# ---------------------------------------------------------
# email_module/email_engine.py
# Email send + inbound processing - replaces email/email_engine.js
# ---------------------------------------------------------
from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from ai.memory import get_memory, upsert_memory
from ai.sales_bot import generate_response, generate_structured_summary
from core.config import (
    EMAIL_PASS,
    EMAIL_USER,
    EMAIL_QUEUE_FILE,
    EVENTS_FILE,
    LEADS_FILE,
    TRACKING_DOMAIN,
)
from core.file_io import read_json, write_json
from email_module.email_events import (
    get_open_mail_event,
    log_mail_interaction,
    open_mail_event,
)

# ---------------------------------------------------------
# 1. SMTP TRANSPORTER
# ---------------------------------------------------------

def _create_smtp() -> smtplib.SMTP_SSL | smtplib.SMTP:
    """
    Creates an SMTP connection. Uses Gmail if credentials available,
    else raises (caller should catch and skip).
    Equivalent to createTransporter() in email_engine.js
    """
    if EMAIL_USER and EMAIL_PASS:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        return server
    raise RuntimeError("No email credentials configured. Set EMAIL_USER and EMAIL_PASS in .env")


def _send_via_smtp(msg: MIMEMultipart) -> None:
    smtp = _create_smtp()
    with smtp:
        smtp.send_message(msg)


# ---------------------------------------------------------
# 2. OUTBOUND MAIL
# ---------------------------------------------------------

async def send_email(lead: dict, subject_or_template: str, body_content: str) -> bool:
    """
    Sends a sales email to the lead.
    Equivalent to sendEmail() in email_engine.js
    """
    subject = subject_or_template or "Follow up from Hivericks"
    body = body_content or "Please ignore this test email."
    to_addr = lead.get("email", "")

    print(f"   📧 EMAIL ENGINE: Sending Email to {to_addr}...")
    print(f"\n================= DRAFT EMAIL START =================")
    print(f"To: {to_addr}")
    print(f"Subject: {subject}")
    print("-----------------------------------------------------")
    print(body.replace("<br>", "\n"))
    print("================= DRAFT EMAIL END ===================\n")

    # Build tracking pixel
    pixel_url = f"{TRACKING_DOMAIN}/track/open?email={to_addr}"

    html_body = f"""
        <div style="font-family: Arial, sans-serif; color: #333;">
            <p>{body.replace(chr(10), '<br>')}</p>
            <br>
            <p>Best regards,<br>Vijay<br>Hivericks Technologies</p>
            <img src="{pixel_url}" width="1" height="1" style="display:none;" />
        </div>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = '"Vijay from XOptimus" <rsvijaypargavan@gmail.com>'
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["X-Hivericks-Bot"] = "true"
    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        _send_via_smtp(msg)
        print("      ✅ Email Sent!")

        # Open event
        lead_key = lead.get("phone") or lead.get("email", "")
        open_mail_event(lead_key, body)

        # CRM sync
        try:
            from crm.crm_connector import push_interaction_to_stream
            await push_interaction_to_stream(lead, "email", {
                "summary": f"Outbound Email: {subject}",
                "intent": "outreach",
                "content": body,
                "nextPrompt": "Waiting for reply",
            })
        except Exception:
            pass

        return True

    except Exception as error:
        print(f"      ❌ Email Failed: {error}")
        return False


# ---------------------------------------------------------
# 3. INBOUND MAIL PROCESSING
# ---------------------------------------------------------

def _clean_email_body(text: str) -> str:
    """
    Strips quoted reply headers from email body.
    Equivalent to cleanEmailBody() in email_engine.js
    """
    if not text:
        return ""
    clean = text

    # "On [date]... wrote:" pattern
    clean = re.split(r"On\s+.+?wrote:", clean, maxsplit=1, flags=re.DOTALL)[0]
    # Outlook header
    clean = re.split(r"From:\s+.+?Sent:\s+.+?Subject:", clean, maxsplit=1, flags=re.DOTALL)[0]
    # Separator
    clean = re.split(r"-----Original Message-----", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    # Quoted lines
    clean = "\n".join(line for line in clean.split("\n") if not line.strip().startswith(">"))

    return clean.strip()


async def process_inbound_email(webhook_payload: dict) -> bool:
    """
    Handles a single inbound email from the queue.
    Equivalent to processInboundEmail() in email_engine.js
    """
    sender = webhook_payload.get("sender", "")
    raw_body = webhook_payload.get("body", "")
    body = _clean_email_body(raw_body)

    print(f"      📩 From {sender}")
    print(f'      📝 Cleaned Body: "{body[:100].replace(chr(10), " ")}..."')

    ignored = ["no-reply", "noreply", "mailer-daemon", "notification", "alert", "team@", "support@"]
    if any(s in sender.lower() for s in ignored):
        print(f"      🚫 BLOCKED: Automated Email from {sender}.")
        return True

    leads: list[dict] = read_json(LEADS_FILE, fallback=[])
    lead = next((l for l in leads if l.get("email") == sender), None)

    if not lead:
        print("      ✨ New Anonymous Lead!")
        lead = {
            "email": sender,
            "phone": "",
            "name": "Anonymous Mail User",
            "status": "MAIL_RECEIVED",
            "source": "ANONYMOUS_MAIL",
            "attempt_count": 0,
            "next_action_due": datetime.now().date().isoformat(),
        }
        leads.append(lead)
    else:
        lead["status"] = "MAIL_RECEIVED"

    write_json(LEADS_FILE, leads)

    lead_id = lead.get("phone") or lead.get("email", "")

    event = get_open_mail_event(lead_id)
    if not event:
        eid = open_mail_event(lead_id, None)
        event = {"event_id": eid}

    log_mail_interaction(event["event_id"], "user", body)
    await upsert_memory(lead_id, {"last_user_message": body})

    memory = await get_memory(lead_id)
    ai_result = await generate_response({
        "userMessage": body,
        "memory": memory,
        "mode": "EMAIL_REPLY",
        "leadContext": lead,
    })
    ai_response: str = (
        ai_result.get("response", "") if isinstance(ai_result, dict) else str(ai_result)
    )
    print(f'      🤖 AI Suggests: "{ai_response[:50]}..."')

    # Send reply
    try:
        reply_msg = MIMEMultipart()
        reply_msg["From"] = '"Vijay from Hivericks" <rsvijaypargavan@gmail.com>'
        reply_msg["To"] = sender
        reply_msg["Subject"] = f"Re: {webhook_payload.get('subject', 'Previous Conversation')}"
        reply_msg.attach(MIMEText(ai_response, "plain"))
        _send_via_smtp(reply_msg)
    except Exception as e:
        print(f"      ❌ Email Reply Failed: {e}")

    log_mail_interaction(event["event_id"], "assistant", ai_response)
    await upsert_memory(lead_id, {"last_bot_message": ai_response})

    # Escalation
    if "call" in body.lower() or "number" in body.lower():
        print("      🚨 MAIL-TO-CALL ESCALATION DETECTED")
        lead["status"] = "MAIL_TO_CALL_REQUESTED"
    else:
        lead["status"] = "MAIL_ENGAGED"

    # Score update
    try:
        from scoring.scoring_engine import calculate_score
        score_result = calculate_score(lead, "WARM", lead["status"])
        lead["score"] = score_result["score"]
        lead["category"] = score_result["category"]
        print(f"      💯 Score Updated: {lead['score']} ({lead['category']})")
    except Exception:
        pass

    write_json(LEADS_FILE, leads)

    try:
        from crm.crm_connector import push_interaction_to_stream
        await push_interaction_to_stream(lead, "email", {
            "summary": f"Inbound Email from {sender}",
            "intent": "request_call" if lead["status"] == "MAIL_TO_CALL_REQUESTED" else "engaged",
            "transcription": body,
            "nextPrompt": ai_response,
        })
    except Exception as crm_err:
        print(f"      ❌ CRM Interaction Push Failed: {crm_err}")

    return True


# ---------------------------------------------------------
# 4. QUEUE PROCESSOR
# ---------------------------------------------------------

async def process_inbound_queue() -> int:
    """
    Processes all items in inbound_email_queue.json.
    Equivalent to processInboundQueue() in email_engine.js
    """
    if not EMAIL_QUEUE_FILE.exists():
        return 0

    try:
        queue: list[dict] = json.loads(EMAIL_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if not queue:
        return 0

    print(f"   📧 EMAIL ENGINE: Processing {len(queue)} Inbound Emails...")

    for item in queue:
        try:
            await process_inbound_email(item)
        except Exception as e:
            print(f"      ❌ Failed to process email from {item.get('sender')}: {e}")

    write_json(EMAIL_QUEUE_FILE, [])
    return len(queue)


# ---------------------------------------------------------
# 5. MAINTENANCE: DEFERRED SUMMARIZATION
# ---------------------------------------------------------

async def finalize_mail_events() -> None:
    """
    Summarises stale (>24h) open mail events.
    Equivalent to finalizeMailEvents() in email_engine.js
    """
    if not EVENTS_FILE.exists():
        return

    try:
        events: list[dict] = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    now = datetime.now(timezone.utc)
    TIMEOUT_HOURS = 24
    BATCH_SIZE = 5

    stale = [
        e for e in events
        if e.get("status") not in ("CLOSED", "FAILED_FINAL", "SKIPPED")
        and (now - _parse_dt(e.get("last_updated") or e.get("timestamp"))).total_seconds() / 3600 > TIMEOUT_HOURS
    ]

    if not stale:
        return

    to_process = stale[:BATCH_SIZE]
    print(f"   🧹 MAIL MAINTENANCE: Summarizing {len(to_process)}/{len(stale)} stale events...")

    leads: list[dict] = read_json(LEADS_FILE, fallback=[])
    leads_updated = False
    events_changed = False

    for evt in to_process:
        summary_data = await _summarize_mail_event_in_memory(evt, events)
        if summary_data:
            events_changed = True
            lead = next(
                (l for l in leads if l.get("phone") == evt.get("lead_id") or l.get("email") == evt.get("lead_id")),
                None,
            )
            if lead:
                lead["last_call_summary"] = json.dumps({
                    "lead_status": "stalled",
                    "generated_at": now.isoformat(),
                    "text_summary": summary_data.get("conversation_summary"),
                })
                lead["status"] = "MAIL_COMPLETE"
                leads_updated = True

                try:
                    from crm.crm_connector import push_interaction_to_stream
                    await push_interaction_to_stream(lead, "email", {
                        "summary": summary_data.get("conversation_summary"),
                        "intent": summary_data.get("user_intent", "email_session_complete"),
                        "transcription": "Email Thread Completed.",
                        "nextPrompt": "N/A",
                    })
                except Exception:
                    pass

    if events_changed:
        write_json(EVENTS_FILE, events)
    if leads_updated:
        write_json(LEADS_FILE, leads)


async def _summarize_mail_event_in_memory(evt: dict, events_list: list[dict]) -> dict | None:
    if evt.get("status") in ("CLOSED", "FAILED_FINAL"):
        return evt.get("structured_analysis")

    evt["summary_attempts"] = (evt.get("summary_attempts") or 0) + 1
    if evt["summary_attempts"] > 3:
        evt["status"] = "FAILED_FINAL"
        return None

    transcript_text = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in evt.get("transcript", [])
        if t.get("role") == "user"
    )

    if not transcript_text:
        evt["status"] = "CLOSED"
        evt["summary"] = "No response to drip."
        evt["structured_analysis"] = {"conversation_summary": "No response to drip.", "user_intent": "no_response"}
        return evt["structured_analysis"]

    try:
        summary_data = await generate_structured_summary(transcript_text)
        evt["summary"] = summary_data.get("conversation_summary")
        evt["structured_analysis"] = summary_data
        evt["status"] = "CLOSED"
        return summary_data
    except Exception:
        return None


def _parse_dt(ts: str | None) -> datetime:
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

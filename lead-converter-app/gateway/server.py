# ---------------------------------------------------------
# gateway/server.py
# Unified Gateway Server (Port 8082)
# Handles: SMS/Email inbound, Dograh call-completed webhooks,
#          voice proxy, health check, email tracking
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from threading import Thread
from typing import Any

import httpx
from flask import Flask, Response, jsonify, request

from core.config import (
    CRM_PUBLIC_URL,
    EMAIL_QUEUE_FILE,
    LEADS_FILE,
    SMS_QUEUE_FILE,
)
from core.file_io import read_json, write_json

app = Flask(__name__)
PORT = 8082
VOICE_SERVER_URL = "http://localhost:3000"

# Idempotency cache (workflow_run_id → True)
_processed_run_ids: set[str] = set()


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "service": "lead-converter-gateway"})


# ─────────────────────────────────────────────────────────────
# SMS INBOUND (Twilio webhook)
# ─────────────────────────────────────────────────────────────

@app.route("/sms", methods=["POST"])
def incoming_sms() -> Response:
    from_num = request.values.get("From", "")
    body = request.values.get("Body", "")
    print(f"\n📨 GATEWAY: Received SMS from {from_num}. Queuing...")
    try:
        queue = read_json(SMS_QUEUE_FILE, fallback=[])
        queue.append({
            "lead_id": from_num,
            "message": body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
        })
        write_json(SMS_QUEUE_FILE, queue)
        print(f"   ✅ SMS Queued. Queue size: {len(queue)}")
    except Exception as e:
        print(f"   ❌ SMS Queue Error: {e}")
    return Response("<Response></Response>", mimetype="text/xml")


# ─────────────────────────────────────────────────────────────
# EMAIL INBOUND
# ─────────────────────────────────────────────────────────────

@app.route("/email", methods=["POST"])
def incoming_email() -> Response:
    data = request.get_json(silent=True) or request.values
    sender = data.get("sender", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    print(f"\n📧 GATEWAY: Received Email from {sender}. Queuing...")
    try:
        queue = read_json(EMAIL_QUEUE_FILE, fallback=[])
        queue.append({
            "sender": sender,
            "subject": subject,
            "body": body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
        })
        write_json(EMAIL_QUEUE_FILE, queue)
    except Exception as e:
        print(f"   ❌ Email Queue Error: {e}")
    return Response("OK", status=200)


# ─────────────────────────────────────────────────────────────
# DOGRAH CALL-COMPLETED WEBHOOK
# Called by Dograh when a voice call ends
# ─────────────────────────────────────────────────────────────

@app.route("/webhooks/call-completed", methods=["POST"])
def call_completed() -> Response:
    """
    Dograh fires this when a call finishes.
    Payload:
      workflow_run_id, phone_number, duration_seconds,
      disposition, recording_url, transcript, context_variables
    """
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    run_id = payload.get("workflow_run_id", "")

    # Idempotency guard
    if run_id and run_id in _processed_run_ids:
        print(f"   ⚠️ WEBHOOK: Already processed run {run_id}. Skipping.")
        return jsonify({"status": "already_processed"})

    if run_id:
        _processed_run_ids.add(run_id)
        # Trim set to avoid unbounded growth
        if len(_processed_run_ids) > 1000:
            _processed_run_ids.clear()

    print(f"\n📞 WEBHOOK: Call completed for run {run_id}")
    print(f"   Phone: {payload.get('phone_number')}")
    print(f"   Duration: {payload.get('duration_seconds')}s")
    print(f"   Disposition: {payload.get('disposition')}")

    # Run the heavy CRM work in a background thread so we ACK Dograh fast
    thread = Thread(target=_handle_call_completion_sync, args=(payload,), daemon=True)
    thread.start()

    return jsonify({"status": "accepted"})


def _handle_call_completion_sync(payload: dict) -> None:
    """Synchronous wrapper to run async CRM logic in background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_handle_call_completion(payload))
    except Exception as e:
        print(f"   ❌ WEBHOOK handler error: {e}")
    finally:
        loop.close()


async def _handle_call_completion(payload: dict) -> None:
    phone = payload.get("phone_number", "").replace("whatsapp:", "")
    disposition = payload.get("disposition", "UNKNOWN")
    duration = payload.get("duration_seconds", 0)
    recording_url = payload.get("recording_url")
    transcript_data = payload.get("transcript", [])
    context_vars = payload.get("context_variables", {})

    # Build transcript text
    if isinstance(transcript_data, list):
        transcript_text = "\n".join(
            f"{t.get('role','?').upper()}: {t.get('content','')}"
            for t in transcript_data
        )
    else:
        transcript_text = str(transcript_data)

    # Map Dograh disposition → local status
    disposition_map = {
        "INTERESTED":     ("CALL_INTERESTED", "In Process"),
        "NOT_INTERESTED": ("CALL_NOT_INTERESTED", "Recycled"),
        "CALLBACK":       ("CALL_CALLBACK", "Assigned"),
        "NO_ANSWER":      ("CALL_NO_ANSWER", "New"),
        "VOICEMAIL":      ("CALL_NO_ANSWER", "New"),
        "BUSY":           ("CALL_BUSY", "New"),
        "DO_NOT_CONTACT": ("DO_NOT_CONTACT", "Recycled"),
        "COMPLETED":      ("CALL_COMPLETED", "In Process"),
    }
    local_status, crm_status = disposition_map.get(
        disposition.upper(), ("CALL_COMPLETED", "In Process")
    )

    # ── Update local leads.json ──────────────────────────────
    try:
        leads = read_json(LEADS_FILE, fallback=[])
        clean_phone = phone.replace("+", "").lstrip("91")  # strip country code for matching
        lead = None
        for l in leads:
            l_phone = (l.get("phone") or "").replace("+", "").lstrip("91")
            if l_phone == clean_phone or l.get("phone") == phone:
                lead = l
                break

        if lead:
            lead["status"] = local_status
            lead["last_call_summary"] = {
                "text_summary": transcript_text[:500],
                "disposition": disposition,
                "duration_seconds": duration,
                "recording_url": recording_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            lead["last_contacted_at"] = datetime.now(timezone.utc).isoformat()
            # Score update
            from scoring.scoring_engine import calculate_score
            intent = "HOT" if disposition == "INTERESTED" else "WARM" if disposition == "CALLBACK" else "COLD"
            sc = calculate_score(lead, intent, local_status)
            lead["score"] = sc["score"]
            lead["category"] = sc["category"]
            write_json(LEADS_FILE, leads)
            print(f"   ✅ Lead updated locally: {lead.get('name')} → {local_status} (score {sc['score']})")
        else:
            print(f"   ⚠️ Lead not found locally for phone {phone}")
    except Exception as e:
        print(f"   ❌ Local lead update failed: {e}")
        lead = None

    # ── Push to EspoCRM ─────────────────────────────────────
    if lead:
        try:
            from crm.crm_connector import sync_lead, log_call_activity
            await sync_lead(lead)
            await log_call_activity(
                lead=lead,
                duration_seconds=duration,
                transcript=transcript_text,
                disposition=disposition,
                recording_url=recording_url,
                crm_status=crm_status,
            )
            print(f"   ✅ CRM updated: {lead.get('name')} → {crm_status}")
        except Exception as e:
            print(f"   ❌ CRM push failed: {e}")

    # ── Trigger follow-up if INTERESTED ──────────────────────
    if disposition == "INTERESTED" and lead:
        try:
            from sms.sms_engine import send_product_whatsapp
            await send_product_whatsapp(lead)
            print(f"   📱 WhatsApp follow-up sent to {lead.get('name')}")
        except Exception as e:
            print(f"   ⚠️ WhatsApp follow-up skipped: {e}")


# ─────────────────────────────────────────────────────────────
# VOICE PROXY (to internal call_server on port 3000)
# ─────────────────────────────────────────────────────────────

@app.route("/voice", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/voice/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_to_voice(path: str) -> Response:
    target = f"{VOICE_SERVER_URL}/voice"
    if path:
        target = f"{target}/{path}"
    try:
        headers = {k: v for k, v in request.headers if k != "Host"}
        resp = httpx.request(
            method=request.method,
            url=target,
            headers=headers,
            content=request.get_data(),
            params=request.args,
            timeout=30,
        )
        return Response(resp.content, status=resp.status_code,
                        content_type=resp.headers.get("Content-Type", "text/xml"))
    except Exception as e:
        print(f"   ❌ Voice proxy error: {e}")
        return Response("<Response><Say>Service unavailable</Say></Response>",
                        status=503, mimetype="text/xml")


# ─────────────────────────────────────────────────────────────
# EMAIL OPEN TRACKING
# ─────────────────────────────────────────────────────────────

@app.route("/track/open", methods=["GET"])
def track_email_open() -> Response:
    email = request.args.get("email", "")
    if email:
        print(f"   📧 EMAIL OPEN TRACKED: {email}")
        # Update lead status
        try:
            leads = read_json(LEADS_FILE, fallback=[])
            for lead in leads:
                if lead.get("email", "").lower() == email.lower():
                    if lead.get("status") in ("MAIL_IDLE", "MAIL_SENT"):
                        lead["status"] = "MAIL_OPENED"
            write_json(LEADS_FILE, leads)
        except Exception:
            pass
    # Return 1x1 transparent pixel
    pixel = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(pixel, mimetype="image/png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)

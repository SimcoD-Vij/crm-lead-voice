# ---------------------------------------------------------
# orchestrator.py — Main loop
# Drives the 10-attempt voice/SMS/email sales pipeline
# Integrated with Dograh voice engine + EspoCRM
# ---------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.sales_bot import generate_response
from core.config import (
    LEADS_FILE,
    USE_DOGRAH_AI,
    DOGRAH_API_URL,
    DOGRAH_API_KEY,
    DOGRAH_TRIGGER_UUID,
    DOGRAH_WORKFLOW_ID,
    WEBHOOK_BASE_URL,
)
from core.file_io import read_json, write_json
from crm.crm_connector import (
    check_connection,
    pull_new_leads,
    push_lead_update,
    retry_fallback_queue,
)
from email_module.email_engine import send_email
from scoring.scoring_engine import calculate_score
from sms.sms_engine import run_smart_sms_batch
from sms.sms_queue_manager import finalize_sms_sessions, process_inbound_queue as process_sms_queue

# ---------------------------------------------------------
# LOCK FILE
# ---------------------------------------------------------
LOCK_FILE = Path(__file__).resolve().parent / "orchestrator.lock"

subprocesses: list[subprocess.Popen] = []


def _cleanup() -> None:
    print("\n   🛑 ORCHESTRATOR SHUTDOWN...")
    if LOCK_FILE.exists():
        LOCK_FILE.unlink(missing_ok=True)
    for p in subprocesses:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            p.kill()
    sys.exit(0)


signal.signal(signal.SIGINT,  lambda s, f: _cleanup())
signal.signal(signal.SIGTERM, lambda s, f: _cleanup())

if LOCK_FILE.exists():
    try:
        pid = int(LOCK_FILE.read_text().strip())
        import psutil
        if psutil.pid_exists(pid):
            print(f"❌ Orchestrator already running (PID {pid}). Exiting.")
            sys.exit(1)
    except Exception:
        pass

LOCK_FILE.write_text(str(os.getpid()))

# ---------------------------------------------------------
# TIMELINE
# ---------------------------------------------------------
TIMELINE_ACTIONS = [
    {"attempt": 1,  "channel": "VOICE",  "buffer_days": 1},
    {"attempt": 2,  "channel": "SMS",    "buffer_days": 1},
    {"attempt": 3,  "channel": "VOICE",  "buffer_days": 1},
    {"attempt": 4,  "channel": "EMAIL",  "buffer_days": 2},
    {"attempt": 5,  "channel": "VOICE",  "buffer_days": 2},
    {"attempt": 6,  "channel": "SMS",    "buffer_days": 2},
    {"attempt": 7,  "channel": "VOICE",  "buffer_days": 2},
    {"attempt": 8,  "channel": "EMAIL",  "buffer_days": 3},
    {"attempt": 9,  "channel": "VOICE",  "buffer_days": 3},
    {"attempt": 10, "channel": "SMS",    "buffer_days": 3},
]

GRADUATION_STATUSES = {
    "HUMAN_HANDOFF", "DO_NOT_CONTACT", "CALL_INTERESTED",
    "COLD_LEAD", "MAIL_COMPLETED",
}


def _action_for_attempt(attempt: int) -> dict | None:
    for a in TIMELINE_ACTIONS:
        if a["attempt"] == attempt:
            return a
    return None


def _is_graduated(lead: dict) -> bool:
    return lead.get("status", "") in GRADUATION_STATUSES


def _is_due(lead: dict) -> bool:
    due = lead.get("next_action_due")
    if not due:
        return True
    try:
        return datetime.fromisoformat(due).date() <= datetime.now().date()
    except Exception:
        return True


# ---------------------------------------------------------
# CALL TRIGGERING
# ---------------------------------------------------------

async def _trigger_dograh_call(lead: dict) -> bool:
    """Fire an outbound call via Dograh voice engine."""
    from voice.dograh_client import DograhClient
    dc = DograhClient()

    context = {
        "lead_name":    lead.get("name", ""),
        "lead_email":   lead.get("email", ""),
        "lead_status":  lead.get("status", "CALL_IDLE"),
        "lead_score":   lead.get("score", 0),
        "attempt":      lead.get("attempt_count", 1),
        # Webhook: Dograh will POST here when call ends
        "webhook_url":  f"{WEBHOOK_BASE_URL}/webhooks/call-completed",
        "product_name": "XOptimus",
        "product_price": "₹1499",
    }

    print(f"\n☎️  DOGRAH CALL → {lead.get('name')} ({lead.get('phone')})")
    result = await dc.initiate_call(
        trigger_uuid=DOGRAH_TRIGGER_UUID,
        phone_number=lead["phone"],
        context=context,
    )
    run_id = result.get("call_id") or result.get("workflow_run_id")
    if run_id:
        lead["current_run_id"] = run_id
        lead["status"] = "CALL_INITIATED"
        print(f"      ✅ Call initiated. Run ID: {run_id}")
        return True
    return False


async def _trigger_twilio_call(lead: dict) -> bool:
    """Fallback: use raw Twilio TwiML call (no voice cloning)."""
    from voice.voice_engine import dial_lead
    sid = await dial_lead(lead)
    if sid:
        lead["status"] = "CALL_CONNECTED"
        return True
    return False


# ---------------------------------------------------------
# PER-CHANNEL HANDLERS
# ---------------------------------------------------------

async def _run_voice_attempt(lead: dict) -> None:
    phone = lead.get("phone")
    if not phone:
        print(f"   ⚠️ No phone for {lead.get('name')} — skipping voice")
        return

    try:
        if USE_DOGRAH_AI and DOGRAH_TRIGGER_UUID:
            await _trigger_dograh_call(lead)
        else:
            await _trigger_twilio_call(lead)
    except Exception as e:
        print(f"   ❌ Voice attempt failed: {e}")
        lead["status"] = "CALL_NO_ANSWER"


async def _run_sms_attempt(lead: dict) -> None:
    phone = lead.get("phone")
    if not phone:
        return
    try:
        from sms.sms_engine import send_sales_sms
        attempt = lead.get("attempt_count", 1)
        if attempt == 2:
            msg = (
                f"Hi {lead.get('name', 'there').split()[0]}! This is Vijay from Hivericks. "
                f"XOptimus helps protect your battery health — stops overcharging, extends life 2x. "
                f"Only ₹1499. Want to know more? Reply YES 🔋"
            )
        elif attempt == 6:
            msg = (
                f"Hi {lead.get('name', 'there').split()[0]}, our customers see 40%+ longer battery life. "
                f"XOptimus is trusted by 10,000+ users. "
                f"Still available at ₹1499. Reply STOP to opt out."
            )
        else:
            msg = (
                f"Hi {lead.get('name', 'there').split()[0]}, last chance — "
                f"we're closing your file. XOptimus at ₹1499. "
                f"Reply INFO for details or STOP to opt out."
            )
        await send_sales_sms(lead, msg)
        lead["status"] = "SMS_SENT"
    except Exception as e:
        print(f"   ❌ SMS attempt failed: {e}")


async def _run_email_attempt(lead: dict) -> None:
    email = lead.get("email")
    if not email:
        return
    try:
        attempt = lead.get("attempt_count", 1)
        if attempt == 4:
            subject = "🔋 Protect Your Battery — XOptimus Details Inside"
            body = (
                f"Hi {lead.get('name', 'there').split()[0]},<br><br>"
                f"As promised, here are the XOptimus details:<br><br>"
                f"✅ Stops charging at 80% to protect battery chemistry<br>"
                f"✅ Reduces heat during charging by 30%+<br>"
                f"✅ Compatible with 6A/12A/16A sockets<br>"
                f"✅ Works with laptops, smartphones, tablets<br><br>"
                f"<b>Price: ₹1499</b> | Free shipping across India<br><br>"
                f"Reply to this email or call us at any time.<br><br>"
                f"Best,<br>Vijay | Hivericks Technologies"
            )
        else:
            subject = "📊 Battery Case Study — Real Customer Results"
            body = (
                f"Hi {lead.get('name', 'there').split()[0]},<br><br>"
                f"One of our customers extended their laptop battery from 2 hours to 4.5 hours "
                f"simply by using XOptimus for 3 months.<br><br>"
                f"The science: Li-Ion batteries degrade fastest above 80% charge. "
                f"XOptimus stops at exactly 80% every time.<br><br>"
                f"Only ₹1499. <a href='https://hivericks.com/xoptimus'>Order here</a><br><br>"
                f"Best,<br>Vijay | Hivericks Technologies"
            )
        await send_email(lead, subject, body)
        lead["status"] = "MAIL_SENT"
    except Exception as e:
        print(f"   ❌ Email attempt failed: {e}")


# ---------------------------------------------------------
# MARK ACTION COMPLETE
# ---------------------------------------------------------

async def _mark_action_complete(lead: dict, action: dict) -> None:
    """Advances attempt count and sets next_action_due."""
    attempt = lead.get("attempt_count", 0) + 1
    lead["attempt_count"] = attempt
    lead["last_contacted_at"] = datetime.now(timezone.utc).isoformat()

    buffer = action.get("buffer_days", 1)
    lead["next_action_due"] = (datetime.now() + timedelta(days=buffer)).date().isoformat()

    # Score
    try:
        sc = calculate_score(lead, "WARM", lead.get("status", ""))
        lead["score"] = sc["score"]
        lead["category"] = sc["category"]
    except Exception:
        pass

    # CRM sync
    try:
        await push_lead_update(lead, {
            "status": _map_crm_status(lead.get("status", "")),
        })
    except Exception as e:
        print(f"   ⚠️ CRM update skipped: {e}")


def _map_crm_status(s: str) -> str:
    return {
        "CALL_INITIATED":    "In Process",
        "CALL_INTERESTED":   "In Process",
        "CALL_NOT_INTERESTED": "Recycled",
        "CALL_COMPLETED":    "In Process",
        "CALL_NO_ANSWER":    "New",
        "SMS_SENT":          "In Process",
        "MAIL_SENT":         "In Process",
        "DO_NOT_CONTACT":    "Recycled",
        "HUMAN_HANDOFF":     "Assigned",
        "COLD_LEAD":         "Recycled",
    }.get(s, "Assigned")


# ---------------------------------------------------------
# PRIORITY OVERRIDES (lead replied to SMS/email wanting a call)
# ---------------------------------------------------------

async def process_priority_actions(leads: list[dict]) -> bool:
    updated = False
    for lead in leads:
        if _is_graduated(lead):
            continue
        s = lead.get("status", "")
        if s in ("SMS_TO_CALL_REQUESTED", "MAIL_TO_CALL_REQUESTED"):
            print(f"\n   🚨 PRIORITY: Calling {lead.get('name')} immediately (requested callback)")
            try:
                if USE_DOGRAH_AI and DOGRAH_TRIGGER_UUID:
                    await _trigger_dograh_call(lead)
                else:
                    await _trigger_twilio_call(lead)
                updated = True
            except Exception as e:
                print(f"      ❌ Priority call failed: {e}")
    return updated


# ---------------------------------------------------------
# POST-CALL CLEANUP (from Twilio-mode calls without webhook)
# ---------------------------------------------------------

async def process_post_call_actions(leads: list[dict]) -> bool:
    updated = False
    for lead in leads:
        if _is_graduated(lead):
            continue
        s = lead.get("status", "")
        # Twilio-mode: these transition automatically
        if s == "CALL_NO_ANSWER":
            lead["status"] = "SMS_IDLE"
            updated = True
        elif s == "CALL_COMPLETED":
            lead["status"] = "MAIL_IDLE"
            updated = True
        # Dograh-mode: CALL_INITIATED stays until webhook fires
        # If initiated > 15min ago with no update, reset
        elif s == "CALL_INITIATED":
            initiated = lead.get("last_contacted_at", "")
            if initiated:
                try:
                    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(initiated)
                    if elapsed.total_seconds() > 900:  # 15 min timeout
                        print(f"   ⏰ Call timeout for {lead.get('name')} — resetting to NO_ANSWER")
                        lead["status"] = "CALL_NO_ANSWER"
                        updated = True
                except Exception:
                    pass
    return updated


# ---------------------------------------------------------
# MAIN PULSE
# ---------------------------------------------------------

async def run_pulse(leads: list[dict]) -> bool:
    """One iteration of the main orchestration loop."""
    updated = False

    # Priority first
    priority_updated = await process_priority_actions(leads)
    updated = updated or priority_updated

    # Post-call cleanup
    cleanup_updated = await process_post_call_actions(leads)
    updated = updated or cleanup_updated

    # Process inbound SMS queue
    try:
        await process_sms_queue()
    except Exception as e:
        print(f"   ⚠️ SMS queue processing error: {e}")

    # Main batch
    today = datetime.now().date().isoformat()
    batch_count = 0
    MAX_BATCH = int(os.environ.get("MAX_BATCH_SIZE", "5"))  # Max calls per pulse

    for lead in leads:
        if batch_count >= MAX_BATCH:
            break
        if _is_graduated(lead):
            continue
        if not _is_due(lead):
            continue

        attempt = lead.get("attempt_count", 0) + 1
        action = _action_for_attempt(attempt)

        if not action:
            # 10 attempts exhausted
            lead["status"] = "COLD_LEAD"
            lead["category"] = "COLD"
            updated = True
            print(f"   🥶 {lead.get('name')} exhausted all 10 attempts → COLD_LEAD")
            continue

        channel = action["channel"]
        name = lead.get("name", "Unknown")
        print(f"\n   📌 Processing {name} | Attempt {attempt} | Channel: {channel}")

        if channel == "VOICE":
            await _run_voice_attempt(lead)
            batch_count += 1
        elif channel == "SMS":
            await _run_sms_attempt(lead)
        elif channel == "EMAIL":
            await _run_email_attempt(lead)

        await _mark_action_complete(lead, action)
        updated = True

    # Retry any failed CRM operations
    try:
        await retry_fallback_queue()
    except Exception:
        pass

    return updated


# ---------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------

async def main_loop() -> None:
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   SIMCO VOICE CRM — ORCHESTRATOR STARTED             ║")
    print(f"║   Dograh AI: {'ENABLED' if USE_DOGRAH_AI else 'DISABLED (Twilio TTS)'}   ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    # Check CRM connection
    crm_ok = await check_connection()
    print(f"   CRM Connection: {'✅ Connected' if crm_ok else '⚠️ Not connected (will retry)'}")

    # Pull initial leads from CRM if local file is empty
    leads = read_json(LEADS_FILE, fallback=[])
    if not leads and crm_ok:
        print("   📥 Pulling leads from CRM...")
        crm_leads = await pull_new_leads(limit=100)
        if crm_leads:
            write_json(LEADS_FILE, crm_leads)
            leads = crm_leads
            print(f"   ✅ {len(leads)} leads loaded from CRM.")

    pulse_interval = int(os.environ.get("PULSE_INTERVAL_SECONDS", "30"))
    print(f"   ⏱️ Pulse interval: {pulse_interval}s | Max batch: {os.environ.get('MAX_BATCH_SIZE', '5')} calls/pulse\n")

    while True:
        try:
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n{'='*55}")
            print(f"  🌀 PULSE @ {now} | Leads: {len(leads)}")
            print(f"{'='*55}")

            leads = read_json(LEADS_FILE, fallback=[])

            # Pull fresh CRM leads every 10 pulses (hourly if 30s pulse)
            pulse_count = getattr(main_loop, "_pulse_count", 0) + 1
            main_loop._pulse_count = pulse_count
            if pulse_count % 10 == 0 and crm_ok:
                print("   📥 Checking CRM for new leads...")
                crm_leads = await pull_new_leads(50)
                if crm_leads:
                    existing_phones = {l.get("phone") for l in leads}
                    new_ones = [l for l in crm_leads if l.get("phone") not in existing_phones]
                    if new_ones:
                        leads.extend(new_ones)
                        print(f"   ➕ {len(new_ones)} new leads imported from CRM")

            updated = await run_pulse(leads)

            if updated:
                write_json(LEADS_FILE, leads)
                active = sum(1 for l in leads if not _is_graduated(l))
                hot = sum(1 for l in leads if l.get("category") == "HOT")
                print(f"\n   📊 Active: {active} | HOT: {hot} | Total: {len(leads)}")

        except Exception as e:
            print(f"\n   ❌ PULSE ERROR: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(pulse_interval)


if __name__ == "__main__":
    asyncio.run(main_loop())

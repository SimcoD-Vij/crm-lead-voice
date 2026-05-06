# sms/sms_engine.py — Twilio WhatsApp/SMS sender
from __future__ import annotations
import json
from datetime import datetime, timezone
from twilio.rest import Client as TwilioClient
from core.config import SMS_HISTORY_FILE, TWILIO_AUTH, TWILIO_SID, TWILIO_WHATSAPP_FROM, TWILIO_PHONE
from core.file_io import read_json, write_json

_twilio_client = None

def _get_client():
    global _twilio_client
    if _twilio_client is None:
        _twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
    return _twilio_client

def is_valid_mobile(lead):
    phone = lead.get("phone") or ""
    return len("".join(c for c in phone if c.isdigit())) >= 10

def log_sms_session(lead_id, role, content):
    history = {}
    if SMS_HISTORY_FILE.exists():
        try:
            history = json.loads(SMS_HISTORY_FILE.read_text())
        except Exception:
            pass
    if lead_id not in history:
        history[lead_id] = []
    history[lead_id].append({"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()})
    SMS_HISTORY_FILE.write_text(json.dumps(history, indent=2))

async def send_sales_sms(lead, message, use_whatsapp=True):
    phone = lead.get("phone", "")
    if not phone:
        return False
    if not TWILIO_SID or not TWILIO_AUTH:
        print(f"   [DRY-RUN] SMS to {phone}: {message}")
        return True
    try:
        client = _get_client()
        if use_whatsapp and phone.startswith("+"):
            msg = client.messages.create(body=message, from_=TWILIO_WHATSAPP_FROM, to=f"whatsapp:{phone}")
        else:
            msg = client.messages.create(body=message, from_=TWILIO_PHONE, to=phone)
        print(f"   SMS sent to {lead.get('name')} SID:{msg.sid}")
        log_sms_session(phone, "assistant", message)
        return True
    except Exception as e:
        print(f"   SMS failed: {e}")
        return False

async def send_product_whatsapp(lead):
    name = (lead.get("name") or "there").split()[0]
    msg = (f"Hi {name}! Vijay from Hivericks.\n\nXOptimus details:\n"
           f"* Stops at 80% - extends battery 2x\n* Reduces heat 30%+\n* All socket types\n\n"
           f"Price: Rs.1499 | hivericks.com/xoptimus\nReply with questions!")
    return await send_sales_sms(lead, msg, use_whatsapp=True)

async def run_smart_sms_batch(leads):
    sms_due = [l for l in leads if l.get("status") == "SMS_IDLE" and is_valid_mobile(l)]
    for lead in sms_due[:10]:
        name = (lead.get("name") or "there").split()[0]
        msg = (f"Hi {name}, Vijay from Hivericks. Tried calling - missed you. "
               f"XOptimus 2x battery life - Rs.1499. Reply YES to learn more!")
        if await send_sales_sms(lead, msg):
            lead["status"] = "SMS_SENT"

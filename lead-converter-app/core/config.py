# core/config.py — unified config for Docker + local dev
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Try to load .env from /app or up to 4 levels up (safe for Docker and local dev)
_search_paths = [Path("/app/.env")]
_p = Path(__file__).resolve()
for _ in range(5):
    _p = _p.parent
    _search_paths.append(_p / ".env")

for _path in _search_paths:
    if _path.exists():
        load_dotenv(_path); break

# ── Paths ───────────────────────────────────────────────────
# /data is a Docker volume mount for persistence
_DATA = Path(os.environ.get("DATA_DIR", "/data"))
_APP  = Path("/app")

PROCESSED_LEADS_DIR = _DATA / "processed_leads"
LEADS_FILE          = PROCESSED_LEADS_DIR / "clean_leads.json"
EVENTS_FILE         = PROCESSED_LEADS_DIR / "lead-events.json"
SMS_HISTORY_FILE    = _DATA / "sms" / "sms_history.json"
SMS_QUEUE_FILE      = _DATA / "sms" / "inbound_sms_queue.json"
ACTIVE_WINDOWS_FILE = _DATA / "sms" / "active_conversations.json"
EMAIL_QUEUE_FILE    = _DATA / "email" / "inbound_email_queue.json"
MEMORY_FILE         = _DATA / "memory.json"
VOICE_CONVO_DIR     = _APP / "voice" / "voice_conversations"
CALL_LOGS_FILE      = _APP / "voice" / "call_logs.json"
SUMMARY_CALLS_FILE  = _APP / "voice" / "summary_calls.json"

# ── AI / Ollama ─────────────────────────────────────────────
OLLAMA_URL          = os.environ.get("OLLAMA_URL", "http://ollama:11434/api/chat")
OLLAMA_GENERATE_URL = OLLAMA_URL.replace("/chat", "/generate")
MODEL               = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
TIMEOUT_MS          = 30_000
MAX_PROMPT_TOKENS   = 3500

# ── Ports ───────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "8082"))

# ── Twilio ──────────────────────────────────────────────────
TWILIO_SID           = os.environ.get("TWILIO_SID", "")
TWILIO_AUTH          = os.environ.get("TWILIO_AUTH", "")
TWILIO_PHONE         = os.environ.get("TWILIO_PHONE", "")
TWILIO_WHATSAPP_FROM = f"whatsapp:{TWILIO_PHONE}" if TWILIO_PHONE else "whatsapp:+14155238886"

# ── Email ───────────────────────────────────────────────────
EMAIL_USER      = os.environ.get("EMAIL_USER", "")
EMAIL_PASS      = os.environ.get("EMAIL_PASS", "")
TRACKING_DOMAIN = os.environ.get("TRACKING_DOMAIN", "http://lead-converter:8082")

# ── CRM ─────────────────────────────────────────────────────
CRM_PUBLIC_URL = os.environ.get("CRM_PUBLIC_URL", "http://espocrm")
CRM_BASE_URL = CRM_PUBLIC_URL.rstrip("/") + "/api"

# ── Dograh ──────────────────────────────────────────────────
USE_DOGRAH_AI        = os.environ.get("USE_DOGRAH_AI", "true").lower() == "true"
DOGRAH_API_URL       = os.environ.get("DOGRAH_API_URL", "http://dograh-api:8000")
DOGRAH_API_KEY       = os.environ.get("DOGRAH_API_KEY", "")
DOGRAH_TRIGGER_UUID  = os.environ.get("DOGRAH_TRIGGER_UUID", "")
DOGRAH_WORKFLOW_ID   = os.environ.get("DOGRAH_WORKFLOW_ID", "")
WEBHOOK_BASE_URL     = os.environ.get("WEBHOOK_BASE_URL", "http://lead-converter:8082")

# ── MinIO ───────────────────────────────────────────────────
MINIO_ENDPOINT   = os.environ.get("MINIO_ENDPOINT", "minio")
MINIO_PORT       = int(os.environ.get("MINIO_PORT", "9000"))
MINIO_USE_SSL    = os.environ.get("MINIO_USE_SSL", "false").lower() == "true"
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET     = os.environ.get("MINIO_BUCKET", "voice-audio")

# ── Ngrok fallback ──────────────────────────────────────────
NGROK_DOMAIN    = os.environ.get("NGROK_DOMAIN", "")
NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "")
SERVER_URL      = os.environ.get("SERVER_URL", "")
ABSTRACT_API_KEY = os.environ.get("ABSTRACT_API_KEY", "")

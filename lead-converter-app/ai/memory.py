# ---------------------------------------------------------
# ai/memory.py
# Lead conversation memory - replaces agent/memory.js
# ---------------------------------------------------------
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import LEADS_FILE, MEMORY_FILE
from core.file_io import read_json, write_json


def _ensure_storage() -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text("{}", encoding="utf-8")


def _read_all() -> dict:
    _ensure_storage()
    try:
        raw = MEMORY_FILE.read_text(encoding="utf-8")
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict) -> None:
    _ensure_storage()
    write_json(MEMORY_FILE, data)


async def get_memory(lead_id: str) -> dict[str, Any]:
    """
    Returns {'history': [...], 'summaryContext': '...', 'status': '...'}
    Equivalent to getMemory() in agent/memory.js
    """
    db = _read_all()
    active = db.get(lead_id, {"history": [], "status": "NEW"})

    history = active.get("history", [])
    if not isinstance(history, list):
        history = []

    # Long-term context: pull from clean_leads.json
    summary_context = ""
    if LEADS_FILE.exists():
        try:
            leads = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
            clean_id = lead_id.replace("whatsapp:", "")
            lead = next(
                (l for l in leads if l.get("phone") in (lead_id, clean_id)), None
            )
            if lead and lead.get("last_call_summary"):
                s = lead["last_call_summary"]
                if isinstance(s, str):
                    summary_context = s
                else:
                    summary_context = (
                        f"PREVIOUS SUMMARY: {s.get('summary', 'N/A')}. "
                        f"User Intent was: {s.get('intent', 'Unknown')}."
                    )
        except Exception as e:
            print(f"⚠️ Error reading lead summary: {e}")

    return {
        "history": history,
        "summaryContext": summary_context,
        "status": active.get("status", "NEW"),
    }


async def upsert_memory(lead_id: str, patch: dict) -> dict:
    """
    Merges patch into existing memory for lead_id.
    Keeps only last 20 history turns.
    Equivalent to upsertMemory() in agent/memory.js
    """
    from datetime import datetime, timezone

    db = _read_all()
    prev = db.get(lead_id, {})

    current_history = prev.get("history", [])
    if not isinstance(current_history, list):
        current_history = []

    new_history = current_history
    if "history" in patch and isinstance(patch["history"], list):
        new_history = current_history + patch["history"]
        if len(new_history) > 20:
            new_history = new_history[-20:]

    updated = {
        **prev,
        **patch,
        "history": new_history,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db[lead_id] = updated
    _write_all(db)
    return updated

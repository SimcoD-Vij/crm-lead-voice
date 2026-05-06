# ---------------------------------------------------------
# email_module/email_events.py
# Mail thread event tracking - replaces email/email_events.js
# ---------------------------------------------------------
from __future__ import annotations

from datetime import datetime, timezone

from ai.sales_bot import generate_structured_summary, generate_text_summary
from core.config import EVENTS_FILE
from core.file_io import read_json, write_json


def _read_events() -> list[dict]:
    return read_json(EVENTS_FILE, fallback=[])


def _write_events(events: list[dict]) -> None:
    write_json(EVENTS_FILE, events)


def open_mail_event(lead_id: str, initial_context: str | None = None) -> str:
    """
    Opens a new MAIL thread event.
    Equivalent to openMailEvent() in email_events.js
    """
    events = _read_events()
    ts = datetime.now(timezone.utc).isoformat()
    event_id = f"evt_mail_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    new_event: dict = {
        "event_id": event_id,
        "lead_id": lead_id,
        "channel": "MAIL",
        "type": "MAIL_THREAD_OPEN",
        "timestamp": ts,
        "status": "OPEN",
        "transcript": [],
        "summary": None,
    }

    if initial_context:
        new_event["transcript"].append({
            "role": "assistant",
            "content": initial_context,
            "timestamp": ts,
        })

    events.append(new_event)
    _write_events(events)
    return event_id


def log_mail_interaction(event_id: str, role: str, content: str) -> bool:
    """
    Appends a message to the mail event transcript.
    Equivalent to logMailInteraction() in email_events.js
    """
    events = _read_events()
    evt = next((e for e in events if e["event_id"] == event_id), None)
    if not evt:
        return False

    ts = datetime.now(timezone.utc).isoformat()
    evt.setdefault("transcript", []).append({"role": role, "content": content, "timestamp": ts})
    evt["last_updated"] = ts
    _write_events(events)
    return True


def get_open_mail_event(lead_id: str) -> dict | None:
    """
    Returns the first OPEN mail event for a lead.
    Equivalent to getOpenMailEvent() in email_events.js
    """
    events = _read_events()
    return next(
        (e for e in events if e.get("lead_id") == lead_id and e.get("channel") == "MAIL" and e.get("status") == "OPEN"),
        None,
    )


async def summarize_mail_event(event_id: str) -> dict | None:
    """
    Generates a structured summary for a mail event and marks it CLOSED.
    Equivalent to summarizeMailEvent() in email_events.js
    """
    events = _read_events()
    evt = next((e for e in events if e["event_id"] == event_id), None)
    if not evt:
        return None

    if evt.get("status") in ("CLOSED", "FAILED_FINAL"):
        return evt.get("structured_analysis") or {"conversation_summary": evt.get("summary")}

    evt["summary_attempts"] = (evt.get("summary_attempts") or 0) + 1
    if evt["summary_attempts"] > 3:
        print(f"      ⛔ Event {event_id} exceeded max summary attempts. Marking FAILED_FINAL.")
        evt["status"] = "FAILED_FINAL"
        evt["failure_reason"] = "MAX_ATTEMPTS_EXCEEDED"
        _write_events(events)
        return None

    _write_events(events)  # Persist attempt count lock

    transcript_text = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in evt.get("transcript", [])
        if t.get("role") == "user"
    )

    if not transcript_text:
        evt["status"] = "CLOSED"
        evt["summary"] = "Lead did not respond to the email drip."
        evt["structured_analysis"] = {
            "interest_level": "low",
            "user_intent": "no_response",
            "objections": "none",
            "next_action": "continue_drip",
            "conversation_summary": "Lead did not respond to the email drip.",
        }
        _write_events(events)
        print(f"      ⏩ Event {event_id} closed (No User Response).")
        return evt["structured_analysis"]

    print(f"      📝 Generating Summary for Event {event_id} (Attempt {evt['summary_attempts']})...")

    try:
        summary_data = await generate_structured_summary(transcript_text)
        if summary_data.get("user_intent") == "error_parsing":
            fallback = await generate_text_summary(transcript_text)
            summary_data["conversation_summary"] = fallback

        evt["summary"] = summary_data.get("conversation_summary")
        evt["structured_analysis"] = summary_data
        evt["status"] = "CLOSED"
        print(f"      ✅ Event Summarized and Closed: {event_id}")
    except Exception as error:
        print(f"      ❌ Summary Failed for {event_id}: {error}")

    _write_events(events)
    return evt.get("structured_analysis")

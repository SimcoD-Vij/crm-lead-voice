# ---------------------------------------------------------
# crm/crm_connector.py
# EspoCRM integration — sync leads, push events, log calls
# ---------------------------------------------------------
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import CRM_BASE_URL, LEADS_FILE
from core.file_io import read_json, write_json

# Fallback queue for when CRM is down
_CRM_FALLBACK_QUEUE: list[dict] = []


def _auth_header() -> dict[str, str]:
    """Basic Auth header for EspoCRM admin user."""
    token = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {token}"}


def _map_lead_status(status: str | None) -> str:
    if not status:
        return "New"
    mappings = {
        "CALL_IDLE":         "New",
        "CALL_CONNECTED":    "In Process",
        "CALL_INTERESTED":   "In Process",
        "CALL_NOT_INTERESTED": "Recycled",
        "CALL_COMPLETED":    "In Process",
        "CALL_NO_ANSWER":    "New",
        "CALL_CALLBACK":     "Assigned",
        "DO_NOT_CONTACT":    "Recycled",
        "SMS_IDLE":          "New",
        "SMS_SENT":          "In Process",
        "NEW_INBOUND":       "New",
        "HUMAN_HANDOFF":     "Assigned",
        "COLD_LEAD":         "Recycled",
    }
    return mappings.get(status, "Assigned")


async def check_connection() -> bool:
    """Checks if EspoCRM is reachable."""
    if not CRM_BASE_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{CRM_BASE_URL}/v1/Lead", headers=_auth_header())
        return r.status_code < 500
    except Exception:
        return False


async def sync_lead(lead: dict) -> str | None:
    """
    Ensures lead exists in CRM and returns its server ID.
    Creates the lead if not found.
    """
    if not CRM_BASE_URL:
        return None
    headers = _auth_header()

    # 1. Check existing lead_id
    if lead.get("lead_id"):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{CRM_BASE_URL}/v1/Lead/{lead['lead_id']}", headers=headers)
            if r.status_code == 200:
                return lead["lead_id"]
        except Exception:
            pass

    # 2. Search by phone / email
    try:
        params: dict[str, Any] = {"select": "id", "limit": 1}
        if lead.get("phone"):
            raw = lead["phone"].replace("+", "")
            params["where[0][type]"] = "in"
            params["where[0][attribute]"] = "phoneNumber"
            params["where[0][value][]"] = [lead["phone"], raw]
        elif lead.get("email"):
            params["where[0][type]"] = "equals"
            params["where[0][attribute]"] = "emailAddress"
            params["where[0][value]"] = lead["email"]

        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{CRM_BASE_URL}/v1/Lead", headers=headers, params=params)
        data = r.json()
        if data.get("list"):
            found_id = data["list"][0]["id"]
            lead["lead_id"] = found_id
            print(f"   🔄 CRM: Found {lead.get('name')} → ID {found_id}")
            return found_id
    except Exception as e:
        print(f"   ⚠️ CRM search failed: {e}")

    # 3. Create new lead
    try:
        name = lead.get("name", "Unknown")
        parts = name.split(" ", 1) if " " in name else [name, ""]
        payload: dict[str, Any] = {
            "firstName": parts[0],
            "lastName": parts[1] if parts[1] else "Lead",
            "source": "Other",
            "status": _map_lead_status(lead.get("status")),
        }
        if lead.get("phone"):
            payload["phoneNumber"] = lead["phone"]
        if lead.get("email"):
            payload["emailAddress"] = lead["email"]

        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(f"{CRM_BASE_URL}/v1/Lead", json=payload, headers=headers)
        new_id = r.json().get("id")
        if new_id:
            lead["lead_id"] = new_id
            print(f"   📥 CRM: Created {name} → ID {new_id}")
        return new_id
    except Exception as e:
        print(f"   ❌ CRM create failed: {e}")
        return None


async def push_lead_update(lead: dict, update: dict) -> None:
    """Updates a lead's fields in EspoCRM."""
    if not CRM_BASE_URL:
        return
    server_id = await sync_lead(lead)
    if not server_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.patch(
                f"{CRM_BASE_URL}/v1/Lead/{server_id}",
                json=update,
                headers=_auth_header(),
            )
    except Exception as e:
        print(f"   ⚠️ CRM update failed: {e}")


async def log_call_activity(
    lead: dict,
    duration_seconds: int,
    transcript: str,
    disposition: str,
    recording_url: str | None = None,
    crm_status: str = "In Process",
) -> None:
    """
    Logs a completed AI voice call as a CRM Call activity on the lead.
    Also updates the lead status field.
    """
    if not CRM_BASE_URL:
        print("   ⚠️ CRM not configured — call activity not logged.")
        return

    server_id = await sync_lead(lead)
    if not server_id:
        # Queue for retry
        _CRM_FALLBACK_QUEUE.append({
            "type": "call_log",
            "lead_id": lead.get("lead_id"),
            "payload": {
                "duration": duration_seconds,
                "transcript": transcript,
                "disposition": disposition,
                "recording_url": recording_url,
            },
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"   ⚠️ CRM unreachable — queued call log for retry ({len(_CRM_FALLBACK_QUEUE)} pending)")
        return

    headers = _auth_header()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Create Call activity ────────────────────────────────
    call_payload: dict[str, Any] = {
        "name": f"AI Voice Call — {timestamp}",
        "status": "Held",
        "direction": "Outbound",
        "duration": max(1, duration_seconds // 60),  # EspoCRM uses minutes
        "description": (
            f"Disposition: {disposition}\n"
            f"Duration: {duration_seconds}s\n"
            f"{'Recording: ' + recording_url if recording_url else ''}\n\n"
            f"--- TRANSCRIPT ---\n{transcript[:2000]}"
        ),
        "parentType": "Lead",
        "parentId": server_id,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{CRM_BASE_URL}/v1/Call", json=call_payload, headers=headers)
        if r.status_code not in (200, 201):
            print(f"   ⚠️ CRM Call log returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"   ❌ CRM Call log failed: {e}")

    # ── Update lead status ──────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.patch(
                f"{CRM_BASE_URL}/v1/Lead/{server_id}",
                json={
                    "status": crm_status,
                    "description": f"Last AI call: {timestamp} | Disposition: {disposition}",
                },
                headers=headers,
            )
    except Exception as e:
        print(f"   ❌ CRM status update failed: {e}")


async def pull_new_leads(limit: int = 100) -> list[dict]:
    """Pulls fresh leads from EspoCRM (status = New)."""
    if not CRM_BASE_URL:
        return []
    try:
        params = {
            "select": "id,firstName,lastName,phoneNumber,emailAddress,status",
            "where[0][type]": "equals",
            "where[0][attribute]": "status",
            "where[0][value]": "New",
            "limit": limit,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{CRM_BASE_URL}/v1/Lead", headers=_auth_header(), params=params)
        data = r.json()
        raw_leads = data.get("list", [])

        leads = []
        for l in raw_leads:
            name = f"{l.get('firstName', '')} {l.get('lastName', '')}".strip()
            leads.append({
                "lead_id": l["id"],
                "name": name or "Unknown",
                "phone": l.get("phoneNumber", ""),
                "email": l.get("emailAddress", ""),
                "status": "CALL_IDLE",
                "attempt_count": 0,
                "score": 0,
                "category": "COLD",
                "source": "CRM",
                "imported_at": datetime.now(timezone.utc).isoformat(),
            })

        print(f"   📥 CRM: Pulled {len(leads)} new leads.")
        return leads
    except Exception as e:
        print(f"   ❌ CRM pull failed: {e}")
        return []


async def push_unified_event(lead: dict, event_type: str, data: dict) -> None:
    """Generic event pusher — logs any event as a Note on the lead."""
    if not CRM_BASE_URL:
        return
    server_id = await sync_lead(lead)
    if not server_id:
        return
    try:
        note_body = f"**{event_type}**\n\n"
        for k, v in data.items():
            note_body += f"- {k}: {v}\n"
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{CRM_BASE_URL}/v1/Note",
                json={
                    "post": note_body,
                    "parentType": "Lead",
                    "parentId": server_id,
                },
                headers=_auth_header(),
            )
    except Exception as e:
        print(f"   ⚠️ CRM event push failed: {e}")


async def retry_fallback_queue() -> None:
    """Retries any queued CRM operations that failed due to connectivity."""
    global _CRM_FALLBACK_QUEUE
    if not _CRM_FALLBACK_QUEUE:
        return
    print(f"   🔄 Retrying {len(_CRM_FALLBACK_QUEUE)} queued CRM operations...")
    remaining = []
    for item in _CRM_FALLBACK_QUEUE:
        try:
            if item["type"] == "call_log":
                # Reconstruct lead for sync
                fake_lead = {"lead_id": item["lead_id"]}
                p = item["payload"]
                await log_call_activity(
                    lead=fake_lead,
                    duration_seconds=p["duration"],
                    transcript=p["transcript"],
                    disposition=p["disposition"],
                    recording_url=p.get("recording_url"),
                )
        except Exception:
            remaining.append(item)
    _CRM_FALLBACK_QUEUE = remaining
    if remaining:
        print(f"   ⚠️ {len(remaining)} CRM operations still pending.")

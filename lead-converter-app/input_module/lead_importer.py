# ---------------------------------------------------------
# input_module/lead_importer.py
# Standalone lead importer script - replaces input/lead_importer.js
# ---------------------------------------------------------
import re
from datetime import datetime, timezone

from core.config import LEADS_FILE
from core.file_io import read_json, write_json

BAD_DATA_FILE = LEADS_FILE.parent / "rejected_leads.json"


def normalize_phone(phone: str, country_code: str = "IN") -> str | None:
    if not phone:
        return None
    raw = re.sub(r"[^0-9+]", "", str(phone))
    return raw if len(raw) >= 10 else None


def validate_email(email: str) -> str | None:
    if not email:
        return None
    clean = email.strip().lower()
    if re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", clean):
        return clean
    return None


def process_lead(raw_lead: dict) -> None:
    print(f"\n🚀 Processing: {raw_lead.get('name', 'Unknown')}...")
    valid_phone = normalize_phone(raw_lead.get("phone"), raw_lead.get("country", "IN"))
    valid_email = validate_email(raw_lead.get("email"))

    if not valid_phone and not valid_email:
        print("   ❌ Rejected: No valid Phone OR Email.")
        return

    clean_lead = {
        "name": raw_lead.get("name", "Unknown").strip(),
        "phone": valid_phone,
        "email": valid_email,
        "attempt_count": 0,
        "next_action_due": datetime.now().date().isoformat(),
        "score": 0,
        "category": "COLD",
        "source": "SYSTEM",
        "status": "PENDING",
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }

    leads = read_json(LEADS_FILE, fallback=[])
    exists = any(
        (l.get("phone") and valid_phone and l["phone"] == valid_phone) or
        (l.get("email") and valid_email and l["email"] == valid_email)
        for l in leads
    )

    if not exists:
        leads.append(clean_lead)
        write_json(LEADS_FILE, leads)
        print("   ✅ Lead Saved.")
    else:
        print("      ⚠️ Duplicate skipped.")


if __name__ == "__main__":
    test_leads = [
        {"name": "Vijay R", "phone": "7604896187", "email": "vijay@example.com", "country": "IN"},
        {"name": "Only Email", "phone": "000", "email": "only@test.com", "country": "IN"},
        {"name": "Only Phone", "phone": "9876543210", "email": "bad-email", "country": "IN"},
        {"name": "Ghost User", "phone": "000", "email": "bad-email", "country": "IN"},
    ]
    if LEADS_FILE.exists():
        LEADS_FILE.unlink()
    for l in test_leads:
        process_lead(l)
    print("\n🏁 Import Complete.")

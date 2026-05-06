# ---------------------------------------------------------
# utils/unlock_lead.py
# Python equivalent of unlock_lead.js
# Usage: python -m utils.unlock_lead [phone_number]
# ---------------------------------------------------------
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Paths
_ROOT = Path(__file__).resolve().parents[1]
LEADS_FILE = _ROOT / "processed_leads" / "clean_leads.json"

def unlock_leads(target_phone=None):
    if not LEADS_FILE.exists():
        print(f"❌ Error: {LEADS_FILE} not found")
        return

    with open(LEADS_FILE, "r", encoding="utf-8") as f:
        leads = json.load(f)

    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()

    unlocked_count = 0

    if target_phone:
        # Unlock specific lead
        lead = next((l for l in leads if l.get("phone") == target_phone or target_phone in l.get("phone", "")), None)

        if not lead:
            print(f"❌ Lead not found: {target_phone}")
            print("\nAvailable leads:")
            for l in leads[:5]:
                print(f"  - {l.get('name')}: {l.get('phone')} (Status: {l.get('status')})")
            return

        print(f"\n🔓 Unlocking Lead: {lead.get('name')} ({lead.get('phone')})")
        print(f"   Current Status: {lead.get('status')}")
        print(f"   Last Action: {lead.get('last_action_date')}")

        # Reset daily lock
        lead["last_action_date"] = yesterday
        lead["next_action_due"] = today
        
        # Also set to a "ready" status if it's graduated
        if lead.get("status") in ("MAIL_COMPLETED", "COLD_LEAD", "DO_NOT_CONTACT"):
             lead["status"] = "CALL_IDLE"
             lead["attempt_count"] = 0

        print(f"\n✅ Lead Unlocked!")
        print(f"   Next Action Due: {today}")
        print(f"   Ready for orchestrator to process")
        unlocked_count = 1
    else:
        # Unlock all leads
        print(f"\n🔓 Unlocking ALL leads...")
        for lead in leads:
            if lead.get("last_action_date") == today:
                lead["last_action_date"] = yesterday
                lead["next_action_due"] = today
                unlocked_count += 1

        print(f"✅ Unlocked {unlocked_count} lead(s)")

    # Save changes
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2)
    print(f"\n💾 Changes saved to {LEADS_FILE.name}\n")

if __name__ == "__main__":
    phone = sys.argv[1] if len(sys.argv) > 1 else None
    unlock_leads(phone)

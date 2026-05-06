# ---------------------------------------------------------
# email_module/reply_monitor.py
# IMAP Inbox Monitor - replaces email/reply_monitor.js
# ---------------------------------------------------------
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email import message_from_bytes
from email.policy import default
import re

from imapclient import IMAPClient

from core.config import EMAIL_PASS, EMAIL_USER
from email_module.email_engine import process_inbound_email

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IMAP_MONITOR")

# IMAP CONFIG
IMAP_HOST = 'imap.gmail.com'
IMAP_PORT = 993

_is_scanning = False

async def monitor_inbox() -> None:
    """
    Checks the Inbox for new (UNSEEN) emails.
    Replaces monitorInbox() in reply_monitor.js
    """
    global _is_scanning
    if _is_scanning:
        logger.info("   🔒 IMAP Scan already in progress.")
        return
    
    if not EMAIL_USER or not EMAIL_PASS:
        logger.warning("   ⚠️ IMAP monitoring skipped: No credentials configured.")
        return

    _is_scanning = True
    logger.info("📬 Checking Inbox for New Emails...")

    try:
        with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as client:
            client.login(EMAIL_USER, EMAIL_PASS)
            client.select_folder('INBOX')

            # Search for unseen messages
            messages = client.search(['UNSEEN'])

            if not messages:
                # logger.info("   (No new emails)")
                return

            logger.info(f"   🔎 Found {len(messages)} new message(s). Processing...")

            # Fetch messages
            response = client.fetch(messages, ['RFC822', 'FLAGS'])

            for uid, data in response.items():
                raw_email = data[b'RFC822']
                msg = message_from_bytes(raw_email, policy=default)

                from_address = msg.get('From', '')
                match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_address)
                clean_from = match.group(0) if match else from_address

                subject = msg.get('Subject', 'No Subject')
                
                # Get body text
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode(errors='replace')
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode(errors='replace')

                # 🛑 Loop Protection (Header Based)
                if msg.get('X-Hivericks-Bot') == 'true':
                    logger.info(f"   🛑 Skipping Msg #{uid}: Detected X-Hivericks-Bot Header (My Own Reply).")
                    client.add_flags(uid, ['\\Seen'])
                    continue

                logger.info(f"   📩 IMAP Ingress: {clean_from} | Subject: {subject}")

                # DELEGATE TO ENGINE
                await process_inbound_email({
                    "sender": clean_from,
                    "subject": subject,
                    "body": body_text.strip()
                })

                # Mark Seen only after processing
                client.add_flags(uid, ['\\Seen'])

    except Exception as e:
        logger.error(f"   ❌ IMAP ERROR: {e}")
    finally:
        _is_scanning = False

if __name__ == "__main__":
    import asyncio
    asyncio.run(monitor_inbox())

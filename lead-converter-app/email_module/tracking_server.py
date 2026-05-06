# ---------------------------------------------------------
# email_module/tracking_server.py
# Edge Intelligence Tracking Server - replaces email/tracking_server.js
# ---------------------------------------------------------
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, redirect, request
from user_agents import parse

from core.config import LEADS_FILE
from core.file_io import read_json, write_json

app = Flask(__name__)
PORT = 5000

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TRACKING_SERVER")

# 1x1 Transparent GIF
PIXEL_BIN = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

def _update_lead_stats(email: str, action: str, req: request) -> None:
    """
    Updates lead data with tracking events and device intelligence.
    Equivalent to updateLeadStats() in tracking_server.js
    """
    try:
        leads: list[dict] = read_json(LEADS_FILE, fallback=[])
        
        # Find lead by email
        lead = next((l for l in leads if l.get("email") == email), None)
        if not lead:
            logger.warning(f"   ⚠️ Tracking attempt for unknown email: {email}")
            return

        # Capture Edge Intelligence (Device Info)
        ua_string = req.headers.get('User-Agent', '')
        user_agent = parse(ua_string)
        
        device_type = "Mobile" if user_agent.is_mobile else "Tablet" if user_agent.is_tablet else "Desktop" if user_agent.is_pc else "Other"
        os_info = f"{user_agent.os.family} {user_agent.os.version_string}"
        browser_info = f"{user_agent.browser.family} {user_agent.browser.version_string}"
        
        logger.info(f"   🕵️ EDGE DATA: {email} | {action} | {os_info} on {device_type}")

        now_str = datetime.now(timezone.utc).isoformat()

        # Update Flags
        if action == 'OPEN':
            lead['opened'] = True
            lead['last_open_time'] = now_str
        elif action == 'CLICK':
            lead['clicked'] = True
            lead['last_click_time'] = now_str

        # Store Intelligence Log
        if 'edge_data' not in lead:
            lead['edge_data'] = []
            
        lead['edge_data'].append({
            "action": action,
            "time": now_str,
            "ip": req.remote_addr,
            "device": device_type,
            "os": os_info,
            "browser": browser_info
        })

        write_json(LEADS_FILE, leads)
        logger.info(f"   💾 Saved {action} event for {email}")

    except Exception as e:
        logger.error(f"   ❌ Error updating tracking stats: {e}")

@app.route('/track/open')
def track_open():
    """Route for the 1x1 tracking pixel."""
    email = request.args.get('email')
    if email:
        _update_lead_stats(email, 'OPEN', request)
    
    return Response(PIXEL_BIN, mimetype='image/gif')

@app.route('/track/click')
def track_click():
    """Route for click tracking and redirect."""
    email = request.args.get('email')
    destination = request.args.get('dest', 'https://hivericks.com')
    
    if email:
        _update_lead_stats(email, 'CLICK', request)
        
    return redirect(destination)

if __name__ == "__main__":
    logger.info("-----------------------------------------------")
    logger.info(f"📡 Edge Intelligence Server running on Port {PORT}")
    logger.info(f"   Waiting for email opens...")
    logger.info("-----------------------------------------------")
    app.run(host='0.0.0.0', port=PORT)

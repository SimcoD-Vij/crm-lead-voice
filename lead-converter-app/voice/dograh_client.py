# voice/dograh_client.py — Dograh voice engine HTTP client
from __future__ import annotations
from typing import Any
import httpx
from core.config import DOGRAH_API_KEY, DOGRAH_API_URL, DOGRAH_WORKFLOW_ID, WEBHOOK_BASE_URL

class DograhClient:
    def __init__(self, api_url=DOGRAH_API_URL, api_key=DOGRAH_API_KEY):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.base_url = f"{self.api_url}/api/v1"

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key.strip()
        return h

    async def health_check(self):
        async with httpx.AsyncClient(timeout=10) as c:
            return (await c.get(f"{self.api_url}/api/v1/health")).json()

    async def initiate_call(self, trigger_uuid, phone_number, context=None):
        context = context or {}
        context["webhook_url"] = f"{WEBHOOK_BASE_URL}/webhooks/call-completed"
        if DOGRAH_WORKFLOW_ID:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.base_url}/telephony/initiate-call",
                    json={"workflow_id": int(DOGRAH_WORKFLOW_ID), "phone_number": phone_number},
                    headers=self._headers())
            data = r.json()
            return {"call_id": str(data.get("message","")).split()[-1] or "unknown", **data}
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base_url}/public/agent/{trigger_uuid}",
                json={"phone_number": phone_number, "initial_context": context},
                headers=self._headers())
        data = r.json()
        return {"call_id": data.get("workflow_run_id"), **data}

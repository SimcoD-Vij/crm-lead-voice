#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     SIMCO VOICE CRM — LEAD CONVERTER STARTING        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Fix paths: config.py uses /data but WORKDIR is /app ────
export PYTHONPATH=/app

# ── Wait for Dograh ────────────────────────────────────────
DOGRAH="${DOGRAH_API_URL:-http://dograh-api:8000}"
echo "⏳ Waiting for Dograh at $DOGRAH ..."
for i in $(seq 1 40); do
  if curl -sf "$DOGRAH/api/v1/health" >/dev/null 2>&1; then
    echo "✅ Dograh is up!"; break
  fi
  echo "   ... ($i/40) retrying in 5s"; sleep 5
done

# ── Wait for EspoCRM ───────────────────────────────────────
CRM="${CRM_PUBLIC_URL:-http://espocrm}"
echo "⏳ Waiting for EspoCRM at $CRM ..."
for i in $(seq 1 20); do
  if curl -sf "$CRM" >/dev/null 2>&1; then
    echo "✅ EspoCRM is up!"; break
  fi
  echo "   ... ($i/20) retrying in 5s"; sleep 5
done

# ── Ensure data dirs ──────────────────────────────────────
mkdir -p /data/processed_leads /data/sms /data/email /app/voice/voice_conversations

[ -f /data/processed_leads/clean_leads.json ]   || echo "[]"  > /data/processed_leads/clean_leads.json
[ -f /data/processed_leads/lead-events.json ]   || echo "[]"  > /data/processed_leads/lead-events.json
[ -f /data/sms/sms_history.json ]               || echo "{}"  > /data/sms/sms_history.json
[ -f /data/sms/inbound_sms_queue.json ]         || echo "[]"  > /data/sms/inbound_sms_queue.json
[ -f /data/sms/active_conversations.json ]      || echo "[]"  > /data/sms/active_conversations.json
[ -f /data/email/inbound_email_queue.json ]     || echo "[]"  > /data/email/inbound_email_queue.json

# ── Start sub-services ────────────────────────────────────
echo ""
echo "🚀 Starting Voice Call Server on :3000 ..."
python -m flask --app voice.call_server run --host 0.0.0.0 --port 3000 &
VPID=$!

echo "🚀 Starting Email Tracking Server on :5000 ..."
python -m flask --app email_module.tracking_server run --host 0.0.0.0 --port 5000 &
TPID=$!

echo "🚀 Starting Gateway on :8082 ..."
python -m flask --app gateway.server run --host 0.0.0.0 --port 8082 &
GPID=$!

sleep 3

trap 'echo "Shutting down..."; kill $VPID $TPID $GPID 2>/dev/null; exit 0' SIGTERM SIGINT

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         ORCHESTRATOR LOOP STARTING                   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

exec python orchestrator.py

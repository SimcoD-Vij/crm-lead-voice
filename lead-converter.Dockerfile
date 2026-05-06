FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY lead-converter-app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache/pip

COPY lead-converter-app/ ./
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /data/processed_leads /data/sms /data/email /app/voice/voice_conversations && \
    echo "[]" > /data/processed_leads/clean_leads.json && \
    echo "[]" > /data/processed_leads/lead-events.json && \
    echo "{}" > /data/sms/sms_history.json && \
    echo "[]" > /data/sms/inbound_sms_queue.json && \
    echo "[]" > /data/sms/active_conversations.json && \
    echo "[]" > /data/email/inbound_email_queue.json

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
ENV DATA_DIR=/data

EXPOSE 8082 3000 5000

HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -sf http://localhost:8082/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]

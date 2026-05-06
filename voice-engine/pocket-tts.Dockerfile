FROM python:3.12-slim

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Install PocketTTS with CPU-only PyTorch ───────────────────────────────────
# CPU torch is ~2 GB smaller than the CUDA build and sufficient for inference.
RUN pip install --no-cache-dir \
    "pocket-tts>=0.1.0" \
    "uvicorn[standard]>=0.29.0" \
    "numpy>=1.26.0" \
    && pip install --no-cache-dir \
    "torch>=2.5.0" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    && rm -rf /root/.cache/pip

WORKDIR /app

# ── Copy entrypoint and fixed pipecat adapter ─────────────────────────────────
COPY pocket_tts_entrypoint.py /app/pocket_tts_entrypoint.py

# ── Voice files directory (mounted at runtime via volume) ─────────────────────
RUN mkdir -p /voices

# ── Environment ───────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# ── Healthcheck: passes only when model is fully loaded ───────────────────────
HEALTHCHECK --interval=10s --timeout=5s --start-period=480s --retries=48 \
  CMD test -f /tmp/pocket_tts_ready || exit 1

# ── Entrypoint: loads + caches model THEN starts uvicorn ─────────────────────
CMD ["python", "/app/pocket_tts_entrypoint.py"]

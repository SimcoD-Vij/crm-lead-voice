FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pocket-tts and its deps
RUN pip install --no-cache-dir \
    "pocket-tts" \
    "torch>=2.5.0" \
    "uvicorn[standard]" \
    "fastapi" \
    "aiohttp" \
    "python-multipart"

# Pre-create voices directory
RUN mkdir -p /voices

WORKDIR /app

# THE KEY FIX
# Force multiprocessing to use 'fork' and single-worker mode
ENV POCKET_TTS_WORKERS=1
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false

# Custom entrypoint that sets fork method before starting the server
COPY pocket_tts_entrypoint.py /app/pocket_tts_entrypoint.py
COPY pocket_tts_health_patch.py /app/pocket_tts_health_patch.py

EXPOSE 8000

CMD ["python", "/app/pocket_tts_entrypoint.py"]

# Multi-stage Dockerfile
# Stage 1: Builder - Install Python dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install git in builder stage (needed for pip install from git)
RUN apt-get update && apt-get install -y \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY api/requirements.txt .

# Install CPU-only PyTorch FIRST to prevent CUDA/NVIDIA dependencies
# This satisfies torch dependency before other packages try to pull GPU version
RUN pip install --user --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    rm -rf /root/.cache/pip

# Install dependencies to user directory for easy copying
RUN pip install --user --no-cache-dir -r requirements.txt && \
    # Clean up pip cache after installation
    rm -rf /root/.cache/pip

# Copy and install pipecat from local submodule
COPY pipecat /tmp/pipecat
RUN pip install --user --no-cache-dir '/tmp/pipecat[cartesia,deepgram,openai,elevenlabs,groq,google,azure,sarvam,soundfile,silero,webrtc,local-smart-turn-v3,speechmatics,openrouter,camb]' && \
    # Pre-download NLTK punkt_tab tokenizer data (required by pipecat at runtime)
    python -c "import nltk; nltk.download('punkt_tab', quiet=True)" && \
    # Pre-download Silero VAD model
    python -c "import os; from pathlib import Path; import urllib.request; \
    vad_dir = Path('/root/.local/lib/python3.12/site-packages/pipecat/audio/vad/data'); \
    vad_dir.mkdir(parents=True, exist_ok=True); \
    print(f'Downloading Silero VAD to {vad_dir}...'); \
    urllib.request.urlretrieve('https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx', vad_dir / 'silero_vad.onnx')" && \
    # Clean up pip cache and temporary pipecat directory
    rm -rf /root/.cache/pip /tmp/pipecat

# Remove unnecessary Python cache files from installed packages
RUN find /root/.local -type f -name '*.pyc' -delete && \
    find /root/.local -type d -name '__pycache__' -delete && \
    find /root/.local -type f -name '*.pyo' -delete

# Stage 2: Runtime - Minimal image with only runtime dependencies
FROM python:3.12-slim AS runner

WORKDIR /app

# Only install ffmpeg (runtime dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local

# Copy NLTK data (punkt_tab tokenizer) from builder stage
COPY --from=builder /root/nltk_data /root/nltk_data

# Make sure scripts in .local are available
ENV PATH=/root/.local/bin:$PATH

# Set Python to not generate .pyc files in runtime
ENV PYTHONDONTWRITEBYTECODE=1
# Unbuffered output for better container logging
ENV PYTHONUNBUFFERED=1

# Copy application code
COPY ./api ./api
COPY ./scripts/start_services_dev.sh ./scripts/start_services_dev.sh

# Product documentation — read at runtime by the MCP docs tools
# (search_dograh_docs / fetch_dograh_doc) so agents can learn Dograh.
COPY ./docs ./docs

ENV PYTHONPATH=/app

# Disable file logging in Docker - logs go to stdout for docker logs
ENV LOG_TO_FILE=false

# Expose the port FastAPI will run on
EXPOSE 8000

# Run the FastAPI app with uvicorn
CMD ["./scripts/start_services_dev.sh"]
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Pocket TTS and Torch
# Using --no-cache-dir to keep image smaller
RUN pip install --no-cache-dir pocket-tts torch

WORKDIR /app

# The port pocket-tts serve uses
EXPOSE 8000

# Start the server
CMD ["pocket-tts", "serve", "--host", "0.0.0.0", "--port", "8000"]

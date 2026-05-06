# PocketTTS + Dograh — Complete Voice Agent Stack

> **One-command voice agent platform** powered by [Kyutai PocketTTS](https://huggingface.co/kyutai/pocket-tts) for voice cloning, [Dograh](https://github.com/dograh-hq/dograh) for the pipeline orchestration, [Pipecat](https://github.com/pipecat-ai/pipecat) as the real-time audio framework, and [Ollama](https://ollama.com) for local LLM inference.

---

## Table of Contents

1. [What Is This?](#what-is-this)
2. [Architecture Overview](#architecture-overview)
3. [Services at a Glance](#services-at-a-glance)
4. [Prerequisites](#prerequisites)
5. [Quick Start — Single Command Deploy](#quick-start--single-command-deploy)
6. [Configuration Reference](#configuration-reference)
7. [PocketTTS Deep Dive](#pockettts-deep-dive)
   - [How PocketTTS Works](#how-pockettts-works)
   - [Voice Cloning with Your Own Voice](#voice-cloning-with-your-own-voice)
   - [Predefined Voices](#predefined-voices)
   - [The Pipecat Adapter (pocket_tts_fixed.py)](#the-pipecat-adapter-pocket_tts_fixedpy)
   - [Why the Fix Was Needed](#why-the-fix-was-needed)
8. [Dograh Pipeline Deep Dive](#dograh-pipeline-deep-dive)
   - [Call Flow: End-to-End](#call-flow-end-to-end)
   - [STT Providers](#stt-providers)
   - [LLM Providers](#llm-providers)
   - [TTS Providers](#tts-providers)
9. [Using Ollama (Local LLM)](#using-ollama-local-llm)
10. [Managing Voice Files](#managing-voice-files)
11. [Deployment on a Remote Server](#deployment-on-a-remote-server)
12. [Useful Docker Commands](#useful-docker-commands)
13. [Troubleshooting](#troubleshooting)
14. [Bug Fixes Applied in This Stack](#bug-fixes-applied-in-this-stack)

---

## What Is This?

This repository contains a fully Dockerized, production-ready voice agent platform. A caller dials in (or opens a WebRTC tab), speaks to an AI agent, and hears back a voice-cloned response — all running **100% locally** on your machine or server.

**The stack:**

| Layer | Technology |
|-------|-----------|
| Voice input (STT) | Dograh STT / Deepgram / OpenAI Whisper |
| AI brain (LLM) | Ollama (llama3.2) / Dograh / OpenAI |
| Voice output (TTS) | **PocketTTS** (Kyutai voice cloning) |
| Real-time audio | Pipecat framework |
| Orchestration | Dograh (FastAPI + workflow engine) |
| Frontend | Dograh UI (Next.js) |
| Object storage | MinIO (S3-compatible) |
| Database | PostgreSQL + pgvector |
| Message queue | Redis |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Internet / Browser                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ WebRTC / WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Dograh UI  :3010                              │
│              (Next.js — workflow builder + call console)         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP / REST
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Dograh API  :8000                              │
│            (FastAPI + Pipecat pipeline engine)                   │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │   STT    │──▶│     LLM      │──▶│   TTS (PocketTTS)      │  │
│  │ Dograh / │   │ Ollama /     │   │  pocket_tts_fixed.py   │  │
│  │ Deepgram │   │ Dograh /     │   │  (pipecat adapter)     │  │
│  └──────────┘   │ OpenAI       │   └───────────┬────────────┘  │
│                 └──────────────┘               │ HTTP POST      │
└─────────────────────────────────────────────────┼───────────────┘
                                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                 PocketTTS Microservice  :8100                    │
│                                                                  │
│  1. Loads kyutai/pocket-tts model (438 MB) on startup           │
│  2. Pre-caches voice states for /voices/recording_1*.wav        │
│  3. Serves POST /tts → streams raw int16 PCM at 24 kHz          │
└─────────────────────────────────────────────────────────────────┘
          ▲
          │ Volume mount
┌─────────┴───────────────────────────────────────────────────────┐
│  voices_data volume  (your .wav voice recordings live here)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Services at a Glance

| Container | Port (host) | Purpose |
|-----------|-------------|---------|
| `dograh-api` | `8000` | FastAPI backend + Pipecat pipeline |
| `dograh-ui` | `3010` | Next.js frontend |
| `pocket-tts` | `8100` | Kyutai PocketTTS microservice |
| `voice-files` | `8101` | Nginx serving voice WAV files |
| `ollama` | `11434` | Local LLM inference |
| `postgres` | `5432` | Database (internal only) |
| `redis` | `6379` | Job queue (internal only) |
| `minio` | `9000/9001` | Object storage for recordings |
| `cloudflared` | `2000` | Public HTTPS tunnel (optional) |
| `nginx-proxy` | `80/443` | TLS reverse proxy (remote profile) |
| `coturn` | `3478` | TURN server for WebRTC (remote profile) |

---

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Docker Engine | 24.x | Latest stable |
| Docker Compose | v2.x | Latest stable |
| RAM | 8 GB | 16 GB |
| Disk | 20 GB free | 40 GB free |
| CPU | 4 cores | 8+ cores |
| GPU (optional) | NVIDIA with CUDA | RTX 3060+ |
| HuggingFace account | Required | — |

**GPU is optional** — everything runs on CPU, but Ollama inference will be faster with a GPU.

---

## Quick Start — Single Command Deploy

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-org/dograh.git
cd dograh
```

### Step 2 — Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and set **at minimum**:

```env
# Required: HuggingFace token for downloading the PocketTTS model
HF_TOKEN=hf_your_token_here

# Required: Change this before exposing to the internet
OSS_JWT_SECRET=your-long-random-secret-here
```

Get your HF token at: https://huggingface.co/settings/tokens  
*(Free account required — the pocket-tts model is gated but free to access)*

### Step 3 — Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

That's it. The script will:
1. Build all Docker images
2. Start the database and infrastructure
3. Pull the Ollama LLM model (`llama3.2:3b` by default)
4. Start PocketTTS and wait for the model to load (~5 min first run)
5. Start the API and UI
6. Print the URLs when ready

**First run** takes 10–20 minutes due to model downloads:
- `kyutai/pocket-tts` model: ~438 MB
- Ollama `llama3.2:3b`: ~2 GB

Subsequent starts: **under 60 seconds** (models are cached in Docker volumes).

### Step 4 — Open the UI

```
http://localhost:3010
```

---

## Configuration Reference

All configuration is done via environment variables in `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | **required** | HuggingFace API token for model download |
| `OLLAMA_MODEL` | `llama3.2:3b` | Which Ollama model to pull/use |
| `OSS_JWT_SECRET` | `ChangeMeInProduction` | JWT signing secret — **change this** |
| `TURN_SECRET` | `dograh-turn-...` | TURN server secret — **change this** |
| `BACKEND_API_ENDPOINT` | `http://localhost:8000` | Public URL of the API |
| `MINIO_PUBLIC_ENDPOINT` | `http://localhost:9000` | Public URL of MinIO |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO username |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO password |
| `ENABLE_TRACING` | `false` | Enable Langfuse tracing |
| `ENABLE_TELEMETRY` | `false` | Enable PostHog analytics |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## PocketTTS Deep Dive

### How PocketTTS Works

[Kyutai PocketTTS](https://huggingface.co/kyutai/pocket-tts) is a streaming text-to-speech model that supports **zero-shot voice cloning** — it can speak in any voice given a short WAV reference recording.

**The synthesis pipeline:**

```
Text input
    ↓
Sentence tokenizer (SentencePiece)
    ↓
Transformer language model (438 MB)
    ↓
Mimi audio codec decoder
    ↓
Raw PCM audio at 24 kHz (float32 or int16)
    ↓
Streamed in chunks over HTTP to the Pipecat adapter
    ↓
Resampled 24 kHz → 16 kHz (for phone/WebRTC compatibility)
    ↓
Audio frames delivered to the caller
```

**Key properties:**
- **Streaming**: First audio chunk arrives within ~300 ms of sending text
- **Voice cloning**: Uses a WAV prompt file (5–15 seconds) to clone any voice
- **1.3–1.5× real-time**: Generates audio faster than playback speed on CPU
- **Sample rate**: Model outputs 24 kHz; pipeline resamples to 16 kHz

### Voice Cloning with Your Own Voice

1. **Record a clean voice sample** (5–15 seconds, quiet room, WAV format, 16 kHz or higher):

```bash
# Using ffmpeg to record 10 seconds from mic:
ffmpeg -f avfoundation -i ":0" -t 10 -ar 16000 -ac 1 my_voice.wav
```

2. **Place it in the voices volume.** On your local machine, copy it into the Docker volume:

```bash
docker cp my_voice.wav pocket-tts:/voices/my_voice.wav
```

Or if you have a local `voices/` folder mounted, just copy the file there.

3. **Set the voice in Dograh UI:**  
   In the workflow configuration, set **TTS Provider** to `PocketTTS` and **Voice** to `/voices/my_voice.wav`.

4. **The model pre-caches** the two default voice files at startup:
   - `/voices/recording_1_short.wav` — short reference for speed
   - `/voices/recording_1.wav` — full reference for quality

   If you want your custom voice pre-cached too, add it to `pocket_tts_entrypoint.py`:

```python
for wav_file in [
    "/voices/recording_1_short.wav",
    "/voices/recording_1.wav",
    "/voices/my_voice.wav",   # ← add this
]:
```

Then rebuild: `docker compose build pocket-tts && docker compose up -d pocket-tts`

### Predefined Voices

PocketTTS ships with built-in voice presets that require no WAV file:

| Voice ID | Character |
|----------|-----------|
| `alba` | Female, neutral (default) |
| `anna` | Female, warm |
| `vera` | Female, professional |
| `marius` | Male, neutral |
| `charles` | Male, deep |
| `paul` | Male, conversational |
| `cosette` | Female, expressive |
| `jean` | Male, French-accented |
| `javert` | Male, authoritative |
| `fantine` | Female, emotional |
| `george` | Male, friendly |
| `mary` | Female, clear |
| `michael` | Male, young |
| `eve` | Female, energetic |

Set any of these as the **Voice** in your Dograh workflow's TTS configuration.

### The Pipecat Adapter (`pocket_tts_fixed.py`)

This file lives at `pocket_tts_fixed.py` and is bind-mounted into the API container over the default installation:

```
/root/.local/lib/python3.12/site-packages/pipecat/services/pocket_tts.py
```

It is the **bridge** between Dograh's Pipecat pipeline and the PocketTTS microservice.

**Key responsibilities:**

1. **Builds the HTTP POST payload** with `text` and `voice_url`
2. **Streams chunked PCM audio** back from the microservice
3. **Resamples 24 kHz → 16 kHz** using linear interpolation
4. **Yields `TTSAudioRawFrame`** objects into the pipeline
5. **Handles alignment** — PCM samples are 2 bytes each; split chunks must be re-joined

**Class API:**

```python
PocketTTSService(
    api_url="http://pocket-tts:8000",   # PocketTTS microservice URL
    voice_id="alba",                     # Predefined voice or WAV path
    use_enhanced_pipeline=True,          # Apply 1.2× volume boost
    timeout=300,                         # HTTP request timeout seconds
    # Pipecat TTSService kwargs:
    text_filters=[xml_function_tag_filter],
    skip_aggregator_types=["recording_router", "recording"],
)
```

### Why the Fix Was Needed

The original `pocket_tts.py` had **two critical bugs** that caused silence after the first agent turn:

#### Bug 1: Fire-and-Forget `_push_tts_frames`

```python
# ORIGINAL (broken) — fires synthesis in a detached background task:
async def _push_tts_frames(self, src_frame, ...):
    asyncio.create_task(super()._push_tts_frames(src_frame, ...))
```

The detached task held the global semaphore while the pipeline moved on to the next turn. The next synthesis request blocked forever waiting for a lock that would never be released.

**Fix:** Remove the override entirely. The base-class `TTSService._push_tts_frames` correctly awaits the generator.

#### Bug 2: Global Semaphore Cross-Turn Deadlock

```python
# ORIGINAL (broken):
_POCKET_TTS_SEMAPHORE = asyncio.Semaphore(1)  # module-level global
```

A single global lock across all pipeline instances meant one stuck instance blocked all others.

**Fix:** Replace with a **per-instance `asyncio.Lock()`** initialised in `__init__`. Each call session gets its own lock; they're independent.

---

## Dograh Pipeline Deep Dive

### Call Flow: End-to-End

```
Caller speaks
    ↓
[Transport] WebRTC / Twilio / Vonage — audio at 16 kHz μ-law or PCM
    ↓
[VAD] Silero Voice Activity Detection — detects speech start/end
    ↓
[STT] Speech-to-Text — transcribes spoken words
    ↓
[LLM Aggregator] Collects full user turn
    ↓
[LLM] Generates agent response (streaming token-by-token)
    ↓
[TTS Aggregator] Buffers text into sentences for synthesis
    ↓
[TTS — PocketTTS] Synthesises audio, streams back to transport
    ↓
Caller hears the response
    ↓
(Loop: repeat until caller hangs up)
```

### STT Providers

Configure in **Settings → STT** in the Dograh UI:

| Provider | Notes |
|----------|-------|
| `Dograh` | Default — cloud STT via Dograh services |
| `Deepgram` | Best accuracy; needs API key |
| `Deepgram Flux` | Lowest latency; English only |
| `OpenAI Whisper` | Needs OpenAI API key |
| `Speaches` | Self-hosted Whisper server |
| `AssemblyAI` | Good for noisy audio |

### LLM Providers

Configure in **Settings → LLM** in the Dograh UI:

| Provider | Notes |
|----------|-------|
| `Ollama` | **Fully local** — no API key; needs model pulled |
| `Dograh` | Cloud LLM via Dograh services |
| `OpenAI` | GPT-4o, GPT-4 Turbo etc. |
| `Groq` | Ultra-fast inference; cloud |
| `Google` | Gemini models |
| `OpenRouter` | Aggregator for many models |

### TTS Providers

Configure in **Settings → TTS** in the Dograh UI:

| Provider | Notes |
|----------|-------|
| `PocketTTS` | **Local voice cloning** — this stack |
| `Deepgram` | Cloud TTS, low latency |
| `ElevenLabs` | Premium voice quality; cloud |
| `OpenAI` | TTS-1 / TTS-1-HD; cloud |
| `Cartesia` | Ultra-low latency streaming; cloud |
| `Sarvam` | Indian language TTS |

---

## Using Ollama (Local LLM)

### Selecting Ollama in the UI

1. Go to **Settings → LLM**
2. Provider: `Ollama (Local)`
3. Model: `llama3.2:3b` (or whichever you've pulled)
4. Base URL: `http://ollama:11434` (pre-configured)

### Pulling Different Models

```bash
# Pull a model (while containers are running):
docker compose exec ollama ollama pull llama3.2:1b    # 1.3 GB — fastest
docker compose exec ollama ollama pull llama3.2:3b    # 2.0 GB — balanced
docker compose exec ollama ollama pull llama3.1:8b    # 4.7 GB — best quality

# List available models:
docker compose exec ollama ollama list

# Remove a model:
docker compose exec ollama ollama rm llama3.2:1b
```

### Why the First Call Was Slow (Fixed)

Ollama lazy-loads the model on first use, taking ~20 seconds. This stack fixes that by:

1. **`OLLAMA_KEEP_ALIVE=-1`** in docker-compose — prevents model eviction between calls
2. **Warm-up ping in API startup** (`api/app.py` lifespan) — pre-loads the model with an empty `keep_alive=-1` request so it's hot before any call arrives

---

## Managing Voice Files

Voice files are stored in the `voices_data` Docker volume, shared between:
- `pocket-tts` container (reads them for voice cloning)
- `voice-files` container (serves them via HTTP at `:8101`)

### Adding a New Voice File

```bash
# Copy a WAV into the voices volume:
docker cp /path/to/your/voice.wav pocket-tts:/voices/your_voice.wav

# Verify it's accessible:
curl http://localhost:8101/voices/your_voice.wav -I
```

### Listing Existing Voice Files

```bash
docker exec pocket-tts ls -la /voices/
```

### Pre-caching a Voice (Eliminates Latency)

Edit `pocket_tts_entrypoint.py` to add your file to the cache list, then rebuild:

```bash
docker compose build pocket-tts
docker compose up -d pocket-tts
```

---

## Deployment on a Remote Server

### Linux VPS (Ubuntu 22.04 recommended)

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# 2. Clone and configure
git clone https://github.com/your-org/dograh.git
cd dograh
cp .env.example .env
nano .env   # Set HF_TOKEN, OSS_JWT_SECRET, TURN_SECRET, BACKEND_API_ENDPOINT

# 3. Deploy (CPU mode)
chmod +x deploy.sh
./deploy.sh

# 4. Deploy (GPU mode — requires nvidia-container-toolkit)
./deploy.sh --gpu
```

### Setting Up HTTPS (Remote Profile)

Enable the nginx + coturn services:

```bash
# 1. Create certs directory and place your SSL certificate
mkdir -p nginx/certs
cp your-cert.pem nginx/certs/cert.pem
cp your-key.pem  nginx/certs/key.pem

# 2. Create nginx config (see nginx/nginx.conf.example)

# 3. Deploy with remote profile
docker compose --profile remote up -d
```

### Domain Setup

In `.env`, set:
```env
BACKEND_API_ENDPOINT=https://yourdomain.com
MINIO_PUBLIC_ENDPOINT=https://yourdomain.com
```

---

## Useful Docker Commands

```bash
# See all running services and health status
docker compose ps

# Follow all logs
docker compose logs -f

# Follow logs for specific service
docker compose logs -f api
docker compose logs -f pocket-tts
docker compose logs -f ollama

# Restart a single service (e.g. after editing pocket_tts_fixed.py)
docker compose restart api

# Rebuild and restart pocket-tts (e.g. after editing entrypoint)
docker compose build pocket-tts && docker compose up -d pocket-tts

# Open a shell inside a container
docker compose exec api bash
docker compose exec pocket-tts bash
docker compose exec ollama bash

# Check PocketTTS health
curl http://localhost:8100/health

# Check API health
curl http://localhost:8000/api/v1/health

# Stop everything (keep data)
./deploy.sh --down

# Full reset (deletes all data!)
./deploy.sh --reset
```

---

## Troubleshooting

### PocketTTS is not generating audio after the first turn

This was a known bug — it's been fixed in `pocket_tts_fixed.py`.  
Symptoms: You hear the first greeting but all subsequent turns are silent.  
Cause: Global semaphore + fire-and-forget `asyncio.create_task` in the original code.  
See: [Why the Fix Was Needed](#why-the-fix-was-needed).

```bash
# Verify the fix is loaded:
docker exec dograh-api python -c "
import pipecat.services.pocket_tts as m
print('semaphore removed:', not hasattr(m,'_POCKET_TTS_SEMAPHORE'))
print('override removed:', '_push_tts_frames' not in m.PocketTTSService.__dict__)
"
```

### Ollama first call takes 20+ seconds

The model is cold-starting. This is fixed by the warm-up in `api/app.py`. Check it fired:

```bash
docker compose logs api | grep "Ollama.*warmed"
```

If not, restart the API: `docker compose restart api`

### PocketTTS health check keeps failing

```bash
# Check what's happening:
docker compose logs pocket-tts

# Is it still downloading the model?
# Look for: "Loading model from config" or HuggingFace download progress
```

The model downloads ~438 MB on first start. Wait ~5 minutes and check again.

### `HF_TOKEN` error in pocket-tts logs

```
huggingface_hub.errors.GatedRepoError: Access to model kyutai/pocket-tts is restricted
```

You need to:
1. Create a HuggingFace account at https://huggingface.co
2. Accept the model license at https://huggingface.co/kyutai/pocket-tts
3. Create an access token at https://huggingface.co/settings/tokens
4. Set `HF_TOKEN=hf_your_token` in `.env`
5. Restart: `docker compose up -d pocket-tts`

### WebRTC not connecting (local machine only)

If calling from the same machine, ensure your browser supports WebRTC and ports are not blocked by firewall. The TURN server is only needed for remote/NAT scenarios.

### Voice quality is poor or robotic

- Ensure your voice recording is clean (no background noise)
- Use a 10–15 second recording for better cloning
- Keep the recording at 16 kHz mono
- Try the full reference file (`recording_1.wav`) instead of the short one

---

## Bug Fixes Applied in This Stack

This deployment includes several critical fixes over the upstream code:

| File | Bug Fixed |
|------|-----------|
| `pocket_tts_fixed.py` | Global semaphore deadlock — all turns after turn 1 were silent |
| `pocket_tts_fixed.py` | Fire-and-forget `_push_tts_frames` causing orphaned tasks |
| `pocket_tts_fixed.py` | `_remainder_buffer` not initialised in `__init__` |
| `api/app.py` | Ollama 20s cold-start on first call (added keep-alive warm-up) |
| `api/services/pipecat/service_factory.py` | Deprecated `model=` kwarg + duplicate settings in OLLamaLLMService |
| `api/constants.py` | Added `OLLAMA_BASE_URL` as configurable constant |
| `docker-compose.yaml` | Removed Windows-specific absolute paths for portability |

---

## License

This stack is built on open-source components:
- [Dograh](https://github.com/dograh-hq/dograh) — Apache 2.0
- [Pipecat](https://github.com/pipecat-ai/pipecat) — BSD-2-Clause
- [PocketTTS](https://huggingface.co/kyutai/pocket-tts) — CC-BY 4.0
- [Ollama](https://github.com/ollama/ollama) — MIT

---

*Generated by Antigravity — last updated April 2026*

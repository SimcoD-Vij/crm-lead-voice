# Simco Voice CRM — Full Integrated Stack

One docker command to run the entire AI-powered voice sales pipeline.

## What runs when you type `docker compose up --build`

| Service | URL | What it does |
|---------|-----|-------------|
| **Dograh UI** | http://localhost:3010 | Configure voice workflows, LLM, TTS |
| **EspoCRM** | http://localhost:3020 | Lead management (admin/admin) |
| **MinIO** | http://localhost:9001 | Call recordings (minioadmin/minioadmin) |
| **Lead Converter** | http://localhost:8082 | Orchestrator gateway + webhooks |
| **Dograh API** | http://localhost:8000 | Voice engine (internal) |
| **Ollama** | http://localhost:11434 | Local LLM — free + unlimited |
| **PocketTTS** | http://localhost:8100 | Voice cloning TTS (internal) |

## First-time Setup (do once)

### Step 1 — Clone both source repos
```bash
git clone https://github.com/SimcoD-Vij/Lead-converter.git _lc_src
git clone https://github.com/SimcoD-Vij/Voice_TT.git _vt_src
# The build context in docker-compose.yml points to the pre-assembled directories
# voice-engine/ and lead-converter-app/ in this package replace those clones.
```

### Step 2 — Configure environment
```bash
cp .env.example .env
# Edit .env — fill in TWILIO_SID, TWILIO_AUTH, TWILIO_PHONE, HF_TOKEN at minimum
```

### Step 3 — Start the stack
```bash
docker compose up --build
```
First run downloads Ollama model (~5 GB) and PocketTTS model (~1 GB). This takes 5–20 min depending on your internet speed.  
Watch progress: `docker compose logs -f ollama-init pocket-tts`

### Step 4 — Configure Dograh voice engine (one-time)
1. Open http://localhost:3010 → create account
2. **Model Configurations** → LLM:
   - Provider: **Ollama** (or Speaches)
   - base_url: `http://ollama:11434/v1`
   - model: `llama3.1:8b`
   - api_key: `ollama`
3. **Model Configurations** → TTS:
   - Provider: **pocket-tts** (custom)
   - api_url: `http://pocket-tts:8000`
   - voice_file: `/dataset/recording_1_short.wav`
4. **Model Configurations** → STT:
   - Provider: **Deepgram**
   - api_key: (your free Deepgram key from deepgram.com)
5. **Create Workflow** → Outbound Sales Call
   - Add system prompt: "You are Vijay, a friendly sales agent for Hivericks Technologies..."
   - Add `end_call` tool
   - In the workflow JSON, add webhook action pointing to `http://lead-converter:8082/webhooks/call-completed`
6. Copy the **API Key** and **Agent Trigger UUID** into your `.env`

### Step 5 — Set Twilio webhook
```bash
docker compose logs cloudflared | grep trycloudflare.com
```
Copy the `https://xxxx.trycloudflare.com` URL.  
In Twilio console → Phone Numbers → your number → Voice webhook:
```
https://xxxx.trycloudflare.com/voice
```

### Step 6 — Restart with Dograh credentials
```bash
docker compose restart lead-converter
```

### Step 7 — Add leads and watch it work
Add leads to `data/processed_leads/clean_leads.json` or via EspoCRM UI at http://localhost:3020.

The orchestrator will:
1. Call each lead via Dograh (AI voice with cloned voice)
2. After each call, update the CRM automatically
3. Send WhatsApp/SMS/Email based on the 10-step timeline
4. Mark HOT leads for human follow-up in EspoCRM

---

## The 10-Attempt Pipeline

| Attempt | Channel | Wait | Goal |
|---------|---------|------|------|
| 1 | Voice Call | 1 day | Introduction |
| 2 | WhatsApp SMS | 1 day | Soft follow-up |
| 3 | Voice Call | 1 day | Objection handling |
| 4 | Email | 2 days | Detailed benefits |
| 5 | Voice Call | 2 days | Direct close |
| 6 | WhatsApp SMS | 2 days | Social proof |
| 7 | Voice Call | 2 days | Final check-in |
| 8 | Email | 3 days | Case study |
| 9 | Voice Call | 3 days | Re-engagement |
| 10 | WhatsApp SMS | 3 days | Closing file |

## Useful commands

```bash
# View orchestrator activity
docker compose logs lead-converter -f

# View live call pipeline
docker compose logs dograh-api -f

# View Ollama model loading/inference
docker compose logs ollama -f

# Check pocket-tts is ready
docker compose logs pocket-tts -f

# Get the public tunnel URL
docker compose logs cloudflared | grep trycloudflare

# Restart just the orchestrator
docker compose restart lead-converter

# Stop everything
docker compose down

# Stop and wipe all data (fresh start)
docker compose down -v
```

## Lead JSON format
```json
{
  "name": "Ravi Kumar",
  "phone": "+919876543210",
  "email": "ravi@example.com",
  "status": "CALL_IDLE",
  "attempt_count": 0,
  "score": 0,
  "category": "COLD",
  "next_action_due": "2026-05-05"
}
```

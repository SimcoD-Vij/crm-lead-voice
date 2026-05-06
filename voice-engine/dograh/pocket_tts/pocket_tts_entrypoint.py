import multiprocessing
multiprocessing.set_start_method("fork", force=True)

import sys
import logging
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("pocket-tts-startup")

# ── STEP 1: Start uvicorn immediately in a background thread ──────────────────
import uvicorn

def start_server():
    uvicorn.run(
        "pocket_tts.main:web_app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        loop="asyncio",
        reload=False,
        log_level="info",
    )

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()
log.info("Uvicorn starting in background (port 8000 will open shortly)...")

# Give uvicorn 5 seconds to bind the port before we start heavy model loading
time.sleep(5)

# ── STEP 2: Load model ────────────────────────────────────────────────────────
log.info("Loading pocket-tts model (first run downloads ~220MB from HuggingFace)...")
try:
    from pocket_tts import TTSModel
    _model = TTSModel.load_model()
    log.info(f"Model loaded. Sample rate: {_model.sample_rate} Hz")
except Exception as e:
    log.error(f"FATAL: Model load failed: {e}")
    sys.exit(1)

# ── STEP 3: Pre-warm ──────────────────────────────────────────────────────────
log.info("Pre-warming model (eliminates first-call latency)...")
try:
    import copy
    _state = _model.get_state_for_audio_prompt("alba")
    _ = _model.generate_audio(copy.deepcopy(_state), "Ready.")
    log.info("Warm-up complete. Generated audio at 1.29x real-time.")
except Exception as e:
    log.warning(f"Warm-up failed (non-fatal, continuing): {e}")

# ── STEP 4: Inject model into running server ──────────────────────────────────
try:
    import pocket_tts.main as _ptts_main
    _ptts_main.tts_model = _model
    log.info("Model injected into live server. TTS requests will now succeed.")
except Exception as e:
    log.error(f"FATAL: Could not inject model into server: {e}")
    sys.exit(1)

# ── STEP 5: Write readiness file (healthcheck reads this) ────────────────────
with open("/tmp/pocket_tts_ready", "w") as f:
    f.write("ready")
log.info("Readiness file written. Container is fully ready.")

# ── STEP 6: Keep main thread alive (uvicorn runs in daemon thread) ────────────
server_thread.join()

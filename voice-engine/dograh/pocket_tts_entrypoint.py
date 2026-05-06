"""
pocket-tts entrypoint — sequential startup.
Model loads and injects BEFORE uvicorn accepts any requests.
No race condition possible.
"""
import multiprocessing
multiprocessing.set_start_method("fork", force=True)

import sys
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("pocket-tts-startup")

# ── STEP 1: Load model ────────────────────────────────────────────────────────
log.info("Loading pocket-tts model...")
try:
    from pocket_tts import TTSModel
    _model = TTSModel.load_model()
    log.info(f"Model loaded. Sample rate: {_model.sample_rate} Hz")
except Exception as e:
    log.error(f"FATAL: Model load failed: {e}")
    sys.exit(1)

# ── STEP 2: Pre-warm & Pre-cache ─────────────────────────────────────────────
log.info("Pre-warming model and pre-caching voice states...")
try:
    import os
    # 1. Standard pre-warm with built-in voice (no file needed, always works)
    _state = _model._cached_get_state_for_audio_prompt("alba")
    _audio = _model.generate_audio(_state, "Hello, I am ready.")
    log.info(f"Warm-up complete. Generated {len(_audio)} samples.")

    # 2. Pre-cache cloning voice files.
    # docker-compose mounts ./voice-engine/dataset → /dataset in the pocket-tts container
    # lru_cache maxsize=2: first two calls are cached; subsequent calls are instant.
    for wav_file in ["/dataset/recording_1_short.wav", "/dataset/recording_1.wav"]:
        if os.path.exists(wav_file):
            log.info(f"Pre-caching voice state for {wav_file}...")
            _ = _model._cached_get_state_for_audio_prompt(wav_file)
            log.info(f"Voice state cached for {wav_file}")
        else:
            log.warning(f"Voice file not found at {wav_file} — skipping pre-cache")
except Exception as e:
    log.warning(f"Warm-up/Pre-cache failed (non-fatal): {e}")

# ── STEP 3: Inject model into server BEFORE uvicorn starts ───────────────────
try:
    import pocket_tts.main as _ptts_main
    _ptts_main.tts_model = _model
    log.info("Model injected. Server will be ready immediately on start.")
except Exception as e:
    log.error(f"FATAL: Model injection failed: {e}")
    sys.exit(1)

# ── STEP 4: Write readiness file ──────────────────────────────────────────────
with open("/tmp/pocket_tts_ready", "w") as f:
    f.write("ready")
log.info("Readiness file written. Starting uvicorn now.")

# ── STEP 5: Start uvicorn AFTER everything is ready (blocking) ────────────────
import uvicorn
uvicorn.run(
    "pocket_tts.main:web_app",  # Matches verified name in Step 3612
    host="0.0.0.0",
    port=8000,
    workers=1,
    loop="asyncio",
    reload=False,
    log_level="info",
    timeout_keep_alive=120,
)

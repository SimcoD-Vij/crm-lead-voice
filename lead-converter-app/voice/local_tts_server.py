import os
# PyTorch 2.6+ blocked loading custom Python objects by default.
# We trust our local Coqui TTS model downloaded from HuggingFace, so we disable this security restriction.
os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "0"
import torch
import functools
# Global monkeypatch to bypass the security restrictions in newer Torch versions
torch.load = functools.partial(torch.load, weights_only=False)

import io
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# We will load the TTS model globally so it stays warm in memory
try:
    from TTS.api import TTS
except ImportError:
    print("Please install TTS: uv pip install TTS fastapi uvicorn")
    import sys
    sys.exit(1)

app = FastAPI(title="XTTS-v2 Local Voice Cloning API")

# Setup device (Auto-detect GPU)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading XTTS-v2 model onto {device.upper()}...")

# Load excellent zero-shot model that natively supports Tamil (ta) and English
# This download is ~2GB on the first run, then stays cached
tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
print("Model loaded successfully into VRAM/RAM!")

# Our reference voice snippet generated earlier
SPEAKER_WAV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference_voice.wav"))

if not os.path.exists(SPEAKER_WAV_PATH):
    print(f"WARNING: reference_voice.wav not found at {SPEAKER_WAV_PATH}. Voice cloning will fail!")

class TTSRequest(BaseModel):
    text: str
    language: str = "en"  # Using 'en' for XTTS since it processes Tanglish perfectly

@app.post("/synthesize")
async def synthesize_audio(request: TTSRequest):
    """
    Synthesizes the text using the voice clone and streams it back.
    Instead of waiting for the full sentence, you can theoretically yield chunks 
    if passing small chunks, but XTTS generates small sentences fast enough.
    """
    def generate_wav():
        # Generate the raw audio using the cloning model
        wav = tts_model.tts(
            text=request.text,
            speaker_wav=SPEAKER_WAV_PATH, 
            language=request.language
        )
        
        # We need to return standard 24kHz PCM 16-bit WAV bytes
        # PyTorch to bytes conversion (using built in Scipy or Soundfile)
        import numpy as np
        from scipy.io.wavfile import write
        
        byte_io = io.BytesIO()
        # Scale to 16-bit PCM integer range (-32768 to 32767)
        audio_int16 = np.int16(np.array(wav) * 32767)
        write(byte_io, 24000, audio_int16)
        
        byte_io.seek(0)
        yield byte_io.read()

    return StreamingResponse(generate_wav(), media_type="audio/wav")

if __name__ == "__main__":
    print("Starting Zero-Shot Voice Streaming Server on Port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)

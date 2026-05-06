import argparse
import os
import sys

try:
    from pydub import AudioSegment
    from pydub.silence import split_on_silence
except ImportError:
    print("Error: Missing dependencies. Please run:")
    print("python -m pip install pydub")
    sys.exit(1)

def extract_reference_audio(input_file: str, output_file: str = "reference_voice.wav", target_length_sec: int = 15):
    """Extends a short clip to target length by combining non-silent chunks."""
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        return

    print(f"Loading '{input_file}'... (This may take a minute for large files)")
    audio = AudioSegment.from_file(input_file)
    
    # We only need mono audio for TTS reference, and usually 22050Hz or 24000Hz is best
    audio = audio.set_channels(1).set_frame_rate(24000)

    print("Analyzing speech chunks and removing silence...")
    chunks = split_on_silence(
        audio,
        min_silence_len=500,  # 0.5s of silence
        silence_thresh=audio.dBFS - 14, # relative to average volume
        keep_silence=250 # leave a little silence padding
    )

    if not chunks:
        print("Could not detect clear speech chunks. Ensure the audio is speech-heavy.")
        return

    # Combine chunks until we hit the target length (e.g., 10-15 seconds)
    target_ms = target_length_sec * 1000
    combined = AudioSegment.empty()
    
    # Skip the very first chunk just in case it's a cough or intro noise
    start_idx = 1 if len(chunks) > 3 else 0
    
    for chunk in chunks[start_idx:]:
        combined += chunk
        if len(combined) >= target_ms:
            break
            
    # Export as a pristine WAV file
    print(f"Cloning sample prepared! Length: {len(combined)/1000:.2f} seconds.")
    combined.export(output_file, format="wav")
    print(f"✅ Saved perfectly isolated reference voice to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract clean speech for AI Voice Cloning")
    parser.add_argument("input_file", type=str, help="Path to your .m4a or .mp3 file")
    parser.add_argument("--output", type=str, default="reference_voice.wav", help="Output .wav filename")
    
    args = parser.parse_args()
    extract_reference_audio(args.input_file, args.output)

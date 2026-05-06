import requests
import os

def generate_local_voice():
    print("Connecting to PocketTTS to generate your cloned voice file...")
    
    # The URL where PocketTTS is running (mapped to 8100 on your host)
    url = "http://localhost:8100/tts"
    
    # The payload for your sales pitch
    payload = {
        "text": "Hello! This is your cloned voice speaking. I am now generated as a local file on your computer. How do I sound?",
        "voice_url": "http://voice-files/voices/ref_12s.wav"
    }
    
    output_file = "generated_pitch.wav"

    try:
        # Request the TTS generation
        response = requests.post(url, data=payload, stream=True)
        
        if response.status_code == 200:
            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            print(f"Success! Your voice has been generated and saved to: {os.path.abspath(output_file)}")
        else:
            print(f"Error: PocketTTS returned status {response.status_code}")
            print(f"Details: {response.text}")
            
    except Exception as e:
        print(f"Failed to connect to PocketTTS: {e}")
        print("Tip: Make sure 'docker compose' is running and 'pocket-tts' is healthy.")

if __name__ == "__main__":
    generate_local_voice()

# Qwen3-TTS (QwenTTS) Integration

This document describes the integration of the Qwen3-TTS provider into the Dograh platform. This provider allows using custom voice cloning endpoints.

## Configuration

To use QwenTTS, you need to provide the following configuration:

| Field | Description |
|---|---|
| **API URL** | The full URL of your Qwen3-TTS cloning service (e.g., `http://your-server:8000/inferences/voice_clone`). |
| **Voice ID** | The unique ID of the cloned voice you want to use. |
| **API Key** | (Optional) Authentication key if your custom endpoint requires it. |

## Implementation Details

### Backend
- **Service**: Implemented in `pipecat/src/pipecat/services/qwen_tts.py`.
- **Registry**: Configured in `api/services/configuration/registry.py` under the `QWENTTS` provider.
- **Voice Fetching**: Handled locally in `api/routes/user.py` to return a static placeholder voice for selection.

### Frontend
- **Voice Selector**: The UI in `ui/src/components/VoiceSelector.tsx` handles the display and configuration of these custom fields.
- **API Client**: The generated SDK types include support for the `qwentts` provider literal.

## Deployment Notes

### Build from Source
Since QwenTTS is a custom integration, you must build the Dograh images from source to include the code changes:

```bash
# Build local images
docker compose build api ui

# Run the stack
docker compose up
```

### Script Compatibility
All shell scripts must use **LF** line endings to function correctly within the Linux-based Docker containers.

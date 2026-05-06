# ---------------------------------------------------------
# ai/voice_utils.py
# SSML + filler utilities - replaces agent/voice_utils.js
# ---------------------------------------------------------
import random
import re

FILLERS = ["Um, ", "You know, ", "Actually, ", "So, ", "Well, "]


def add_fillers(text: str) -> str:
    """Randomly prepend a human-sounding filler ~30% of the time."""
    if random.random() > 0.7:
        filler = random.choice(FILLERS)
        return filler + text[0].lower() + text[1:]
    return text


def text_to_ssml(text: str) -> str:
    """
    Wraps plain text in SSML for Twilio Polly.
    Equivalent to textToSSML() in agent/voice_utils.js
    """
    clean = re.sub(r"[*#]", "", text)
    human = add_fillers(clean)
    return f"""<speak>
    <break time="200ms"/>
    <prosody rate="105%">
        {human}
    </prosody>
</speak>"""

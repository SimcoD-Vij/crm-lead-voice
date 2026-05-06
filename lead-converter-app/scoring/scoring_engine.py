# ---------------------------------------------------------
# scoring/scoring_engine.py
# Lead scoring - replaces scoring/scoring_engine.js
# ---------------------------------------------------------
from __future__ import annotations

from typing import Any


def calculate_score(lead: dict, intent: str, status: str) -> dict[str, Any]:
    """
    Calculates a score out of 100.
    Weights:  Intent 50% | Status 30% | Efficiency 20%
    Equivalent to calculateScore() in scoring/scoring_engine.js
    """
    score = 0
    i = (intent or "COLD").upper()

    # 1. INTENT SCORE (max 50)
    if i == "NEGATIVE":
        score = 0
    elif i == "HOT":
        score += 50
    elif i == "WARM":
        score += 30
    elif i == "COLD":
        score += 10
    else:
        score += 10

    # Optional: apply transcript-based penalty if embedded
    summary = lead.get("last_call_summary")
    if summary and isinstance(summary, dict) and summary.get("transcript"):
        penalty = analyze_sentiment(summary["transcript"])
        score += penalty

    # 2. STATUS SCORE (max 30)
    s = (status or "").upper()
    HIGH_ENGAGEMENT = {"CALL_CONNECTED", "SMS_ENGAGED", "MAIL_ENGAGED", "CALL_INTERESTED", "HUMAN_HANDOFF"}
    MED_ENGAGEMENT = {"SMS_REPLIED", "SMS_RECEIVED", "MAIL_OPENED", "MAIL_RECEIVED", "CALL_TO_SMS_FOLLOWUP"}
    LOW_ENGAGEMENT = {"SMS_DELIVERED", "MAIL_DELIVERED", "CALL_NO_ANSWER", "CALL_BUSY"}

    if s in HIGH_ENGAGEMENT:
        score += 30
    elif s in MED_ENGAGEMENT:
        score += 20
    elif s in LOW_ENGAGEMENT:
        score += 10
    else:
        score += 5

    # 3. EFFICIENCY SCORE (max 20)
    attempt = lead.get("attempt_count", 0) or 0
    if attempt <= 3:
        score += 20
    elif attempt <= 6:
        score += 10
    elif attempt <= 9:
        score += 5

    # 4. BOUNDS
    score = max(0, min(100, score))

    return {
        "score": score,
        "category": get_category(score),
        "intent_level": i,
    }


def get_category(score: int) -> str:
    if score >= 70:
        return "HOT"
    if score >= 40:
        return "WARM"
    return "COLD"


def analyze_sentiment(transcript: list[dict]) -> int:
    """
    Scans last 3 user / AI turns for negative signals.
    Returns a penalty score (0 or negative).
    Equivalent to analyzeSentiment() in scoring_engine.js
    """
    if not transcript or not isinstance(transcript, list):
        return 0

    negative_keywords = [
        "not worth", "bad", "cheat", "scam", "too high", "expensive",
        "hang up", "don't want", "fraud", "useless", "fake", "cheaper",
    ]
    refusal_keywords = ["cannot assist", "can't answer", "unable to provide", "apologize"]

    user_turns = [t for t in transcript if t.get("role") == "user"][-3:]
    for t in user_turns:
        text = (t.get("text") or "").lower()
        if any(k in text for k in negative_keywords):
            return -50

    ai_turns = [t for t in transcript if t.get("role") == "assistant"][-3:]
    for t in ai_turns:
        text = (t.get("text") or "").lower()
        if any(k in text for k in refusal_keywords):
            return -30

    return 0

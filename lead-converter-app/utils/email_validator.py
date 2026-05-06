# ---------------------------------------------------------
# utils/email_validator.py
# Content validation for emails - replaces utils/emailValidator.js
# ---------------------------------------------------------

def validate_email_content(email_text: str) -> dict[str, bool | str]:
    if not email_text or not isinstance(email_text, str):
        return {"valid": False, "reason": "Empty or non-string email"}

    forbidden_phrases = [
        "google docs",
        "template",
        "system",
        "generated email",
        "replace function",
        "platform doesn't support",
        "draft email start",
        "here is the email",
        "here is a generated",
        "start_email_generation",
    ]

    lower = email_text.lower()
    for phrase in forbidden_phrases:
        if phrase in lower:
            return {"valid": False, "reason": f'Forbidden phrase found: "{phrase}"'}

    if not email_text.lower().startswith("subject:"):
        return {"valid": False, "reason": "Missing 'Subject:' line at start"}

    if "Dear" not in email_text and "Hi " not in email_text and "Hello " not in email_text:
        return {"valid": False, "reason": "Missing professional salutation"}

    if len(email_text) < 10:
        return {"valid": False, "reason": "Email content is virtually empty"}

    return {"valid": True}

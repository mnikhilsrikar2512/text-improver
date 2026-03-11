import re

from fastapi import HTTPException

from app.config import MAX_LENGTH

BLOCKED_PATTERNS = [
    r"\bkill\b",
    r"\bshoot\b",
    r"\bstab\b",
    r"\bterror(?:ist|ism)?\b",
    r"\bfuck(?:ing)?\b",
    r"\bshit\b",
    r"\basshole\b",
    r"\bbitch\b",
    r"\bidiot\b",
    r"\bmoron\b",
]


def validate_input(text):
    cleaned_text = text.strip() if isinstance(text, str) else ""

    if not cleaned_text:
        raise HTTPException(status_code=400, detail="Text is empty")

    if len(cleaned_text) > MAX_LENGTH:
        raise HTTPException(status_code=400, detail="Text too long")

    return cleaned_text


def enforce_guardrails(text: str) -> str:
    lowered = text.lower()

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered):
            raise HTTPException(
                status_code=400,
                detail="Input contains language that cannot be processed for HR rewriting",
            )

    return text

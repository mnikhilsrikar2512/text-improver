import json
import re
from collections import Counter

import redis
from fastapi import HTTPException

from app.config import FEEDBACK_TTL, REQUIRE_REDIS
from app.core.redis_client import redis_client
from app.utils.hash_utils import hash_text

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "please",
    "so",
    "that",
    "the",
    "this",
    "to",
    "we",
    "will",
    "with",
    "would",
    "you",
    "your",
}


def build_feedback_key(text: str) -> str:
    return f"feedback:{hash_text(text)}"


def normalize_feedback_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    cleaned = text.replace("```", "").strip(" \n\t\r\"'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""

    if cleaned[-1] not in ".!?":
        cleaned += "."

    return cleaned


def get_feedback_profile(text: str) -> dict:
    key = build_feedback_key(text)

    try:
        data = redis_client.get(key)
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Feedback service unavailable")
        return _empty_profile()

    if not data:
        return _empty_profile()

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return _empty_profile()

    accepted = [normalize_feedback_text(item) for item in payload.get("accepted_examples", [])]
    rejected = [normalize_feedback_text(item) for item in payload.get("rejected_examples", [])]

    return {
        "accepted_examples": [item for item in accepted if item],
        "rejected_examples": [item for item in rejected if item],
        "accepted_tokens": payload.get("accepted_tokens", {}),
        "rejected_tokens": payload.get("rejected_tokens", {}),
        "version": int(payload.get("version", 0)),
    }


def record_feedback(text: str, accepted_suggestion: str | None = None, rejected_suggestions: list[str] | None = None) -> dict:
    profile = get_feedback_profile(text)
    accepted = profile["accepted_examples"]
    rejected = profile["rejected_examples"]
    accepted_tokens = Counter(profile["accepted_tokens"])
    rejected_tokens = Counter(profile["rejected_tokens"])
    changed = False

    normalized_accepted = normalize_feedback_text(accepted_suggestion or "")
    if normalized_accepted and normalized_accepted not in accepted:
        accepted.append(normalized_accepted)
        accepted_tokens.update(_tokenize(normalized_accepted))
        changed = True

    for suggestion in rejected_suggestions or []:
        normalized_rejected = normalize_feedback_text(suggestion)
        if not normalized_rejected:
            continue
        if normalized_rejected not in rejected:
            rejected.append(normalized_rejected)
            rejected_tokens.update(_tokenize(normalized_rejected))
            changed = True

    version = profile["version"] + (1 if changed else 0)
    payload = {
        "accepted_examples": accepted[-15:],
        "rejected_examples": rejected[-30:],
        "accepted_tokens": dict(accepted_tokens),
        "rejected_tokens": dict(rejected_tokens),
        "version": version,
    }

    key = build_feedback_key(text)
    try:
        redis_client.setex(key, FEEDBACK_TTL, json.dumps(payload))
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Feedback service unavailable")

    return {
        "accepted": len(payload["accepted_examples"]),
        "rejected": len(payload["rejected_examples"]),
        "version": version,
    }


def apply_feedback_learning(suggestions: list[str], feedback_profile: dict) -> list[str]:
    accepted_examples = set(feedback_profile.get("accepted_examples", []))
    rejected_examples = set(feedback_profile.get("rejected_examples", []))
    accepted_tokens = Counter(feedback_profile.get("accepted_tokens", {}))
    rejected_tokens = Counter(feedback_profile.get("rejected_tokens", {}))
    has_feedback = bool(accepted_examples or rejected_examples or accepted_tokens or rejected_tokens)

    if not has_feedback:
        learned = []
        for suggestion in suggestions:
            normalized = normalize_feedback_text(suggestion)
            if normalized and normalized not in learned:
                learned.append(normalized)
        return learned

    ranked = []

    for index, suggestion in enumerate(suggestions):
        normalized = normalize_feedback_text(suggestion)
        if not normalized:
            continue
        if normalized in rejected_examples:
            continue

        tokens = _tokenize(normalized)
        if not tokens and has_feedback:
            continue

        score = 0
        if normalized in accepted_examples:
            score += 1000

        score += sum(accepted_tokens[token] for token in tokens)
        score -= sum(rejected_tokens[token] for token in tokens)
        score += _human_tone_bonus(normalized)

        ranked.append((score, index, normalized))

    ranked.sort(key=lambda item: (-item[0], item[1]))

    learned = []
    for _, _, suggestion in ranked:
        if suggestion not in learned:
            learned.append(suggestion)

    return learned


def feedback_signature(feedback_profile: dict) -> int:
    return int(feedback_profile.get("version", 0))


def build_preference_context(feedback_profile: dict) -> str:
    accepted = feedback_profile.get("accepted_examples", [])[-3:]
    rejected = feedback_profile.get("rejected_examples", [])[-5:]
    parts = []

    if accepted:
        parts.append("Prefer suggestions with a similar tone to:\n- " + "\n- ".join(accepted))
    if rejected:
        parts.append("Avoid suggestions that feel similar to:\n- " + "\n- ".join(rejected))

    return "\n\n".join(parts)


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z']+", text.lower())
        if token not in STOPWORDS and len(token) > 2
    ]


def _human_tone_bonus(text: str) -> int:
    lowered = text.lower()
    score = 0
    for phrase in ("would like", "please", "thank you", "appreciate", "let me know", "not feeling well"):
        if phrase in lowered:
            score += 2
    for stiff in ("formally communicate", "please be informed", "this is to inform", "kindly note"):
        if stiff in lowered:
            score -= 3
    return score


def _empty_profile() -> dict:
    return {
        "accepted_examples": [],
        "rejected_examples": [],
        "accepted_tokens": {},
        "rejected_tokens": {},
        "version": 0,
    }

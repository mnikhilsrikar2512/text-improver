import json
import re

import requests

from app.config import (
    MODEL_NAME,
    MODEL_RETRY,
    MODEL_TEMPERATURE,
    MODEL_TIMEOUT,
    OLLAMA_URL,
    SUGGESTION_COUNT,
    SUGGESTION_POOL_SIZE,
)
from app.services.feedback_service import build_preference_context
from app.services.grammar_service import correct_grammar

VARIATION_HINTS = [
    "Keep the tone natural, clear, and professional.",
    "Use a calm workplace tone that sounds human, not robotic.",
    "Sound polite and polished without becoming overly formal.",
    "Write it the way a thoughtful employee would naturally say it at work.",
    "Make the phrasing warm and professional without adding new facts.",
    "Keep it concise and natural for internal workplace communication.",
    "Prefer plain, clear business English over stiff wording.",
    "Keep the message HR-safe while sounding conversational and respectful.",
]

PROMPT = """
You are an HR communication assistant.

Task:
- Rewrite the full message in natural, polished workplace English.
- Preserve the exact meaning and intent.
- Improve grammar, punctuation, and clarity.
- Keep the output safe for workplace and HR communication.
- Do not add dates, names, policies, or facts that were not in the original message.
- Do not use abusive, insulting, sexual, or threatening language.
- Return {suggestion_pool_size} distinct rewrite options.
- Each option must be a complete rewrite of the whole message.
- Avoid stiff phrases like "This is to inform you" unless they are genuinely natural.
- Prefer wording that sounds human, direct, and respectful.
- Output JSON only.

Variation guidance:
{variation_hint}

Preference guidance:
{preference_hint}

JSON format:
{{
  "suggestions": [
    "rewrite 1",
    "rewrite 2",
    "rewrite 3",
    "rewrite 4",
    "rewrite 5",
    "rewrite 6",
    "rewrite 7",
    "rewrite 8",
    "rewrite 9",
    "rewrite 10"
  ]
}}

Original message:
{text}
"""

MIN_QUALITY_SUGGESTIONS = 3


def call_model(prompt: str, attempt: int) -> str:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "temperature": min(0.8, MODEL_TEMPERATURE + (attempt * 0.05)),
            },
            timeout=MODEL_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.exceptions.RequestException:
        return ""


def parse_output(raw):
    if not raw:
        return []

    raw_text = raw.strip() if isinstance(raw, str) else raw
    parsed = _load_json(raw_text)
    suggestions = _extract_suggestions(parsed)

    if suggestions:
        return suggestions[:SUGGESTION_POOL_SIZE]

    if isinstance(raw_text, str):
        return _extract_plain_text_suggestions(raw_text)[:SUGGESTION_POOL_SIZE]

    return []


def _load_json(raw):
    if not isinstance(raw, str):
        return raw

    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", raw)
        if not match:
            return None

        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _extract_suggestions(parsed):
    if isinstance(parsed, dict):
        suggestions = parsed.get("suggestions")
        if isinstance(suggestions, list):
            return _normalize_suggestions(suggestions)

        response = parsed.get("response")
        if isinstance(response, str):
            return _extract_suggestions(_load_json(response))

        rewritten = parsed.get("rewritten")
        if isinstance(rewritten, str):
            return _normalize_suggestions([rewritten])

        labeled_values = []
        for key, value in parsed.items():
            if not isinstance(value, str):
                continue

            lowered_key = str(key).strip().lower()
            if lowered_key.startswith("rewrite ") or lowered_key.startswith("suggestion "):
                labeled_values.append(value)

        if labeled_values:
            return _normalize_suggestions(labeled_values)

    if isinstance(parsed, list):
        suggestions = []

        for item in parsed:
            if isinstance(item, str):
                suggestions.append(item)
                continue

            if isinstance(item, dict) and isinstance(item.get("rewritten"), str):
                suggestions.append(item["rewritten"])

        return _normalize_suggestions(suggestions)

    return []


def _extract_plain_text_suggestions(raw):
    normalized_raw = raw.replace("\\n", "\n")
    suggestions = []
    saw_list_marker = False

    for line in normalized_raw.splitlines():
        candidate = line.strip()
        if not candidate:
            continue

        if re.match(r"^\d+[\).\-\s]+", candidate):
            saw_list_marker = True

        candidate = re.sub(r"^\d+[\).\-\s]+", "", candidate)
        candidate = candidate.strip("*- ").strip()
        extracted_candidate = _extract_labeled_value(candidate)
        if extracted_candidate != candidate:
            saw_list_marker = True
        candidate = extracted_candidate
        candidate = candidate.strip(" ,")

        if not candidate:
            continue

        lowered = candidate.lower()
        if lowered.startswith("here are") or lowered.startswith("here is"):
            continue
        if lowered.startswith("variation "):
            continue
        if "rewritten version" in lowered or "rewritten versions" in lowered:
            continue
        if candidate == "```" or candidate.startswith("```"):
            continue
        if candidate in {"{", "}", "[", "]", ",", ":", "\"", "'"}:
            continue

        suggestions.append(candidate)

    if saw_list_marker or len(suggestions) > 1:
        return _normalize_suggestions(suggestions)

    return []


def _normalize_suggestions(suggestions):
    normalized = []

    for suggestion in suggestions:
        if not isinstance(suggestion, str):
            continue

        cleaned = suggestion.replace("```", "").strip()
        cleaned = _extract_labeled_value(cleaned)
        cleaned = cleaned.strip(" ,")
        if not cleaned:
            continue

        if cleaned in {"{", "}", "[", "]", ",", ":", "\"", "'"}:
            continue
        if not re.search(r"[A-Za-z]", cleaned):
            continue

        cleaned = correct_grammar(cleaned)

        if cleaned not in normalized:
            normalized.append(cleaned)

    return normalized


def _is_high_quality_suggestion_set(suggestions):
    if len(suggestions) < min(MIN_QUALITY_SUGGESTIONS, SUGGESTION_COUNT):
        return False

    canonical_forms = set()

    for suggestion in suggestions:
        if len(suggestion) < 15:
            return False

        if len(suggestion.split()) < 3:
            return False

        lowered = suggestion.lower()
        if lowered.startswith("rewrite ") or lowered.startswith("suggestion "):
            return False

        canonical = re.sub(r"[^a-z0-9]+", "", lowered)
        if not canonical:
            return False
        if canonical in canonical_forms:
            return False

        canonical_forms.add(canonical)

    return True


def _extract_labeled_value(value):
    labeled_match = re.match(
        r'^"?((rewrite|suggestion)\s*\d+)"?\s*:\s*"?(.+?)"?\s*,?$',
        value,
        flags=re.IGNORECASE,
    )
    if labeled_match:
        return labeled_match.group(3).strip()

    return value


def generate_suggestions(text: str, attempt: int = 0, feedback_profile: dict | None = None) -> tuple[str, list[str]]:
    improved_input = correct_grammar(text)
    variation_hint = VARIATION_HINTS[attempt % len(VARIATION_HINTS)]
    preference_hint = build_preference_context(feedback_profile or {})
    if not preference_hint:
        preference_hint = "No prior user feedback is available. Focus on natural workplace variation."
    prompt = PROMPT.format(
        text=improved_input,
        variation_hint=variation_hint,
        preference_hint=preference_hint,
        suggestion_pool_size=SUGGESTION_POOL_SIZE,
    )

    for _ in range(MODEL_RETRY):
        raw = call_model(prompt, attempt)
        suggestions = parse_output(raw)

        if suggestions and _is_high_quality_suggestion_set(suggestions):
            return improved_input, suggestions[:SUGGESTION_POOL_SIZE]

    return improved_input, []

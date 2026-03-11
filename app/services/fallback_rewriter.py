from app.config import SUGGESTION_POOL_SIZE
from app.services.grammar_service import correct_grammar


INTENT_TEMPLATES = {
    "sick_leave": [
        "I am not feeling well today, so I would like to take leave.",
        "I am feeling unwell today and need to take leave.",
        "As I am not feeling well today, I would like to take the day off.",
        "I am not feeling well today, so I will need to take leave.",
        "I am under the weather today and would like to take leave.",
        "Since I am not feeling well today, I would like to request leave.",
        "I am not feeling well today and will need to take the day off.",
        "I am unwell today, so I would like to apply for leave.",
        "I would like to take leave today as I am not feeling well.",
        "Please treat this as my leave request for today, as I am unwell.",
    ],
    "leave_request": [
        "I would like to request leave for {content}.",
        "Please consider this my leave request for {content}.",
        "I am writing to request leave for {content}.",
        "I would like to take leave for {content}.",
        "I am requesting leave for {content}.",
        "Please approve my leave for {content}.",
        "I would appreciate leave approval for {content}.",
        "I would like to apply for leave for {content}.",
        "Please treat this as my request for leave for {content}.",
        "I am hoping to take leave for {content}.",
    ],
    "gratitude": [
        "Thank you for {content}.",
        "I sincerely appreciate {content}.",
        "Thank you for all your support with {content}.",
        "I truly appreciate {content}.",
        "Many thanks for {content}.",
        "Please accept my sincere thanks for {content}.",
        "I really appreciate your patience and support with {content}.",
        "Thank you for your support with {content}.",
        "I am grateful for {content}.",
        "{content_cap} are greatly appreciated.",
    ],
    "unavailability": [
        "I will be unavailable for {content}.",
        "Please note that I will not be available for {content}.",
        "I wanted to let you know that I will be unavailable for {content}.",
        "I will be unable to attend {content}.",
        "I regret to inform you that I will not be available for {content}.",
        "I won't be available for {content}.",
        "I will not be able to attend {content}.",
        "Please be advised that I will be unavailable for {content}.",
        "I am unable to participate in {content}.",
        "Unfortunately, I won't be available for {content}.",
    ],
    "apology": [
        "I sincerely apologize for {content}.",
        "Please accept my apology for {content}.",
        "I would like to apologize for {content}.",
        "I regret any inconvenience caused by {content}.",
        "Kindly accept my sincere apologies for {content}.",
        "I apologize for any inconvenience caused by {content}.",
        "I am sorry for {content}.",
        "Please accept my regret regarding {content}.",
        "I truly regret {content}.",
        "I am sorry about {content}.",
    ],
    "meeting_request": [
        "I would like to discuss {content}.",
        "Please let me know a convenient time to discuss {content}.",
        "Can we schedule some time to discuss {content}?",
        "Could we schedule a meeting to review {content}?",
        "I would appreciate the chance to talk through {content}.",
        "Please let me know your availability to discuss {content}.",
        "I would like to connect and discuss {content}.",
        "Let me know a suitable time to go over {content}.",
        "I am requesting a meeting to go over {content}.",
        "Please let me know when we can discuss {content}.",
    ],
    "generic": [
        "I would like to share that {content}.",
        "Please note that {content}.",
        "I am writing to inform you that {content}.",
        "I wanted to let you know that {content}.",
        "I would like to mention that {content}.",
        "Kindly note that {content}.",
        "I would like to let you know that {content}.",
        "Please be informed that {content}.",
        "I would like to communicate that {content}.",
        "Just to let you know, {content}.",
    ],
}


def fallback_rewrite(text: str, attempt: int = 0) -> list[str]:
    corrected = correct_grammar(text).strip()
    intent = _detect_intent(corrected)
    content = _normalize_content(_strip_leading_phrase(corrected, intent).rstrip(".").strip(), intent)
    if not content:
        content = corrected.rstrip(".")

    templates = INTENT_TEMPLATES[intent]
    start_index = attempt % len(templates)
    ordered_templates = templates[start_index:] + templates[:start_index]

    suggestions = []

    for template in ordered_templates:
        suggestion = _finalize_sentence(
            template.format(
                content=content,
                content_cap=content[:1].upper() + content[1:] if content else content,
            )
        )
        if suggestion not in suggestions:
            suggestions.append(suggestion)

        if len(suggestions) >= SUGGESTION_POOL_SIZE:
            break

    return suggestions


def _detect_intent(text: str) -> str:
    lowered = text.lower()

    if "thank you" in lowered or "appreciate" in lowered or "grateful" in lowered:
        return "gratitude"
    if (
        "not feeling well" in lowered
        or "not feeling good" in lowered
        or "feeling sick" in lowered
        or "feeling unwell" in lowered
        or "under the weather" in lowered
        or ("sick" in lowered and "leave" in lowered)
        or ("unwell" in lowered and "leave" in lowered)
    ):
        return "sick_leave"
    if "leave" in lowered or "time off" in lowered or "vacation" in lowered:
        return "leave_request"
    if "unavailable" in lowered or "cannot attend" in lowered or "can't attend" in lowered or "not be available" in lowered:
        return "unavailability"
    if "sorry" in lowered or "apolog" in lowered or "regret" in lowered:
        return "apology"
    if "meeting" in lowered or "discuss" in lowered or "schedule" in lowered:
        return "meeting_request"

    return "generic"


def _strip_leading_phrase(text: str, intent: str) -> str:
    lowered = text.lower()
    patterns = {
        "sick_leave": [
            "i am not feeling well today so i need leave",
            "i am not feeling good today so i need leave",
            "i am not feeling well today and need leave",
            "i am not feeling good today and need leave",
            "i am sick today and need leave",
            "i am unwell today and need leave",
            "i need sick leave because i am not feeling well",
        ],
        "leave_request": [
            "i am writing to request leave for ",
            "i would like to request leave for ",
            "please approve my leave for ",
            "i am requesting leave for ",
        ],
        "gratitude": [
            "thank you for ",
            "i appreciate ",
            "we appreciate ",
            "many thanks for ",
        ],
        "unavailability": [
            "i will be unavailable for ",
            "i am unavailable for ",
            "i will not be available for ",
            "i cannot attend ",
            "i can't attend ",
        ],
        "apology": [
            "i apologize for ",
            "i am sorry for ",
            "please accept my apology for ",
        ],
        "meeting_request": [
            "i would like to request a meeting regarding ",
            "i would like to discuss ",
            "please let us discuss ",
            "i would like to schedule a meeting regarding ",
        ],
    }

    for prefix in patterns.get(intent, []):
        if lowered.startswith(prefix):
            return text[len(prefix):]

    return text


def _normalize_content(content: str, intent: str) -> str:
    normalized = content.strip()

    if intent == "gratitude":
        if normalized.lower().startswith("your "):
            return normalized
        return f"your {normalized}"

    if intent == "sick_leave":
        return normalized

    if intent == "meeting_request":
        lowered = normalized.lower()
        if lowered.endswith(" in a meeting"):
            return normalized[:-13].strip()
        if lowered.endswith(" during a meeting"):
            return normalized[:-16].strip()

    return normalized


def _finalize_sentence(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned.endswith("."):
        cleaned += "."
    return cleaned

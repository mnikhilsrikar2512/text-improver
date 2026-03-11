from app.config import SUGGESTION_POOL_SIZE
from app.services.grammar_service import correct_grammar


def fallback_rewrite(text: str, attempt: int = 0) -> list[str]:
    corrected = correct_grammar(text)

    templates = [
        "I would like to formally communicate that {text}.",
        "Please note that {text}.",
        "I am writing to inform you that {text}.",
        "This message is to respectfully state that {text}.",
        "I would like to share that {text}.",
        "Kindly note that {text}.",
        "I would like to respectfully mention that {text}.",
        "Please be informed that {text}.",
        "I would like to submit that {text}.",
        "This is a formal note to share that {text}.",
    ]

    start_index = attempt % len(templates)
    ordered_templates = templates[start_index:] + templates[:start_index]

    suggestions = []

    for template in ordered_templates:
        suggestion = template.format(text=corrected.rstrip("."))
        if suggestion not in suggestions:
            suggestions.append(suggestion)

        if len(suggestions) >= SUGGESTION_POOL_SIZE:
            break

    return suggestions

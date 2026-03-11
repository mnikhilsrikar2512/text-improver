import hashlib

from app.config import CACHE_VERSION, MODEL_NAME, PROMPT_VERSION, SUGGESTION_COUNT, SUGGESTION_POOL_SIZE

def hash_text(text):

    normalized = text.lower().strip()

    return hashlib.sha256(
        normalized.encode()
    ).hexdigest()


def build_cache_key(text):

    return ":".join([
        "rewrite",
        CACHE_VERSION,
        MODEL_NAME,
        PROMPT_VERSION,
        f"batch{SUGGESTION_COUNT}",
        f"pool{SUGGESTION_POOL_SIZE}",
        hash_text(text),
    ])

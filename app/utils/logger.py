import json
import logging
from logging.handlers import RotatingFileHandler
import hashlib

from app.config import AUDIT_LOG_BACKUP_COUNT, AUDIT_LOG_MAX_BYTES, AUDIT_LOG_PATH


audit_logger = logging.getLogger("audit")

if not audit_logger.handlers:
    audit_logger.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(
        AUDIT_LOG_PATH,
        maxBytes=AUDIT_LOG_MAX_BYTES,
        backupCount=AUDIT_LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(file_handler)
    audit_logger.propagate = False


def log_event(
    *,
    source_ip: str,
    input_text: str,
    improved_input: str,
    request_id: str,
    attempt: int,
    selected_index: int,
    suggestions: list[str],
    cached: bool,
    latency_ms: int,
):
    selected_suggestion = suggestions[selected_index] if suggestions else ""
    payload = {
        "request_id": request_id,
        "source_ip": source_ip,
        "input_hash": hashlib.sha256(input_text.encode()).hexdigest(),
        "improved_input_hash": hashlib.sha256(improved_input.encode()).hexdigest(),
        "attempt": attempt,
        "selected_index": selected_index,
        "suggestion_count": len(suggestions),
        "selected_suggestion_hash": hashlib.sha256(selected_suggestion.encode()).hexdigest() if selected_suggestion else "",
        "cached": cached,
        "latency_ms": latency_ms,
    }
    audit_logger.info(json.dumps(payload, ensure_ascii=True))

import time

from fastapi import APIRouter, HTTPException, Request

from app.models.request_models import (
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    ImproveRequest,
    ImproveResponse,
    ReadinessResponse,
)
from app.config import CACHE_VERSION, MODEL_NAME, PROMPT_VERSION, SUGGESTION_COUNT, SUGGESTION_POOL_SIZE
from app.services.ai_rewriter import generate_suggestions
from app.services.cache_service import cache_suggestions, get_cached, is_cache_payload_compatible
from app.services.feedback_service import (
    apply_feedback_learning,
    feedback_signature,
    get_feedback_profile,
    record_feedback,
)
from app.services.fallback_rewriter import fallback_rewrite
from app.services.guardrails import enforce_guardrails, validate_input
from app.services.rate_limiter import check_rate_limit
from app.services.system_health import readiness_status
from app.utils.hash_utils import build_cache_key
from app.utils.logger import log_event

router = APIRouter()


def normalize_suggestions(items):
    normalized = []

    for item in items or []:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
            continue

        if isinstance(item, dict):
            rewritten = item.get("rewritten")
            if isinstance(rewritten, str):
                cleaned = rewritten.strip()
                if cleaned and cleaned not in normalized:
                    normalized.append(cleaned)

    return normalized


def cache_matches_feedback(cached_payload, feedback_profile):
    metadata = cached_payload.get("cache_metadata", {})
    return metadata.get("feedback_version", 0) == feedback_signature(feedback_profile)


def select_attempt_batch(pool, attempt):
    normalized_pool = normalize_suggestions(pool)

    if len(normalized_pool) <= SUGGESTION_COUNT:
        return normalized_pool, 0, {
            "batch_size": len(normalized_pool),
            "pool_size": len(normalized_pool),
            "batch_start": 0,
            "next_attempt": attempt + 1,
            "wrapped": False,
        }

    total_batches = (len(normalized_pool) + SUGGESTION_COUNT - 1) // SUGGESTION_COUNT
    batch_number = attempt % total_batches
    start_index = batch_number * SUGGESTION_COUNT
    batch = normalized_pool[start_index:start_index + SUGGESTION_COUNT]

    return batch, 0, {
        "batch_size": len(batch),
        "pool_size": len(normalized_pool),
        "batch_start": start_index,
        "next_attempt": attempt + 1,
        "wrapped": attempt >= total_batches,
    }


@router.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
def ready():
    readiness = readiness_status()
    if not readiness["ready"]:
        raise HTTPException(status_code=503, detail=readiness)

    return {
        "status": "ready",
        "components": readiness["components"],
    }


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(req: FeedbackRequest):
    original_text = validate_input(req.text)
    guarded_text = enforce_guardrails(original_text)

    learned_preferences = record_feedback(
        guarded_text,
        accepted_suggestion=req.accepted_suggestion,
        rejected_suggestions=req.rejected_suggestions,
    )

    return {
        "status": "recorded",
        "learned_preferences": learned_preferences,
    }


@router.post("/improve-text", response_model=ImproveResponse)
def improve_text(req: ImproveRequest, request: Request):
    start = time.time()
    ip = request.client.host if request.client else "unknown"
    request_id = getattr(request.state, "request_id", "unknown")

    check_rate_limit(ip)

    original_text = validate_input(req.text)
    guarded_text = enforce_guardrails(original_text)
    key = build_cache_key(guarded_text)
    feedback_profile = get_feedback_profile(guarded_text)

    cached_payload = get_cached(key)
    cache_hit = bool(cached_payload)

    should_generate = not cached_payload

    if cached_payload:
        if is_cache_payload_compatible(cached_payload) and cache_matches_feedback(cached_payload, feedback_profile):
            improved_input = cached_payload.get("improved_input", guarded_text)
            suggestions = apply_feedback_learning(
                normalize_suggestions(
                    cached_payload.get("suggestion_pool", cached_payload.get("suggestions", []))
                    if isinstance(cached_payload, dict)
                    else []
                ),
                feedback_profile,
            )
            if feedback_signature(feedback_profile) > 0 and len(suggestions) < SUGGESTION_COUNT:
                cache_hit = False
                should_generate = True
        else:
            cache_hit = False
            improved_input = guarded_text
            suggestions = []
            should_generate = True

    if should_generate:
        improved_input, suggestions = generate_suggestions(guarded_text, req.attempt, feedback_profile=feedback_profile)

        if not suggestions:
            suggestions = fallback_rewrite(improved_input, req.attempt)

        suggestions = apply_feedback_learning(normalize_suggestions(suggestions), feedback_profile)
        cache_suggestions(
            key,
            {
                "improved_input": improved_input,
                "suggestion_pool": suggestions,
                "cache_metadata": {
                    "cache_version": CACHE_VERSION,
                    "model_name": MODEL_NAME,
                    "prompt_version": PROMPT_VERSION,
                    "pool_size": SUGGESTION_POOL_SIZE,
                    "feedback_version": feedback_signature(feedback_profile),
                },
            },
        )

    if not suggestions:
        suggestions = fallback_rewrite(improved_input if cache_hit else guarded_text, req.attempt)
        suggestions = apply_feedback_learning(normalize_suggestions(suggestions), feedback_profile)

    if not suggestions:
        raise HTTPException(status_code=503, detail="No suggestions available at the moment")

    suggestions, selected_index, attempt_metadata = select_attempt_batch(suggestions, req.attempt)
    latency = int((time.time() - start) * 1000)

    log_event(
        source_ip=ip,
        input_text=original_text,
        improved_input=improved_input,
        request_id=request_id,
        attempt=req.attempt,
        selected_index=selected_index,
        suggestions=suggestions,
        cached=cache_hit,
        latency_ms=latency,
    )

    return {
        "original": original_text,
        "improved_input": improved_input,
        "attempt": req.attempt,
        "selected_index": selected_index,
        "selected_suggestion": suggestions[selected_index],
        "suggestions": suggestions,
        "attempt_metadata": attempt_metadata,
        "cached": cache_hit,
        "latency_ms": latency,
    }

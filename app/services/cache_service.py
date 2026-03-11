import json

import redis
from fastapi import HTTPException

from app.config import CACHE_TTL, REQUIRE_REDIS
from app.core.redis_client import redis_client


def get_cached(key: str):
    try:
        data = redis_client.get(key)
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Cache service unavailable")
        return None

    if not data:
        return None

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def cache_suggestions(key: str, payload: dict):
    try:
        redis_client.setex(
            key,
            CACHE_TTL,
            json.dumps(payload),
        )
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Cache service unavailable")
        return


def is_cache_payload_compatible(payload):
    if not isinstance(payload, dict):
        return False

    metadata = payload.get("cache_metadata")

    return isinstance(metadata, dict)

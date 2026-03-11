from __future__ import annotations

from app.config import REQUIRE_REDIS
from app.core.redis_client import ping_redis


def readiness_status() -> dict:
    redis_ok = ping_redis()
    ready = redis_ok or not REQUIRE_REDIS

    return {
        "ready": ready,
        "components": {
            "redis": "ok" if redis_ok else "unavailable",
        },
    }

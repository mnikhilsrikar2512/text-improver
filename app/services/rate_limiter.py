from fastapi import HTTPException
import redis

from app.config import RATE_LIMIT, RATE_WINDOW, REQUIRE_REDIS
from app.core.redis_client import redis_client


def check_rate_limit(ip: str):
    key = f"rate_limit:{ip}"

    try:
        current_count = redis_client.get(key)
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Rate limit service unavailable")
        return

    if current_count and int(current_count) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, RATE_WINDOW)
        pipe.execute()
    except redis.RedisError:
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="Rate limit service unavailable")
        return

import redis

from app.config import REDIS_DB, REDIS_HOST, REDIS_PORT, REDIS_TIMEOUT


redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    socket_connect_timeout=REDIS_TIMEOUT,
    socket_timeout=REDIS_TIMEOUT,
)


def ping_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False

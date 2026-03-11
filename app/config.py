import os


API_TITLE = "AI Text Improver API"
API_VERSION = "3.1.0"
CACHE_VERSION = os.getenv("CACHE_VERSION", "rewrite_v1")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT.lower() == "production"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "llama3")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_TIMEOUT = float(os.getenv("REDIS_TIMEOUT", "1.5"))

CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
SUGGESTION_COUNT = int(os.getenv("SUGGESTION_COUNT", "5"))
SUGGESTION_POOL_SIZE = int(os.getenv("SUGGESTION_POOL_SIZE", "10"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "10"))

RATE_LIMIT = int(os.getenv("RATE_LIMIT", "30"))
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))

MODEL_TIMEOUT = int(os.getenv("MODEL_TIMEOUT", "8"))
MODEL_RETRY = int(os.getenv("MODEL_RETRY", "3"))
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.3"))
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "hr_prompt_v1")

MAX_LENGTH = int(os.getenv("MAX_LENGTH", "1000"))
LANGUAGE_TOOL_LANGUAGE = os.getenv("LANGUAGE_TOOL_LANGUAGE", "en-US")

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "audit.log")
AUDIT_LOG_MAX_BYTES = int(os.getenv("AUDIT_LOG_MAX_BYTES", "10485760"))
AUDIT_LOG_BACKUP_COUNT = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "5"))

REQUIRE_REDIS = os.getenv("REQUIRE_REDIS", "true" if IS_PRODUCTION else "false").lower() == "true"
REQUIRE_LANGUAGE_TOOL = os.getenv("REQUIRE_LANGUAGE_TOOL", "false").lower() == "true"
WARM_DEPENDENCIES_ON_STARTUP = os.getenv("WARM_DEPENDENCIES_ON_STARTUP", "true").lower() == "true"

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

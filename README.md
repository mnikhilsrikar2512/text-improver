# AI Text Improver API

FastAPI service for HR-safe text rewriting using a local Ollama model, Redis-backed caching and rate limiting, grammar correction, audit logging, and attempt-based suggestion pools.

## Overview

This API is designed for integration into internal HR and workflow systems where:

- no external API keys are allowed
- rewrites must stay on local infrastructure
- repeated requests should be cached
- retry attempts should return a fresh batch of suggestions
- unsafe or abusive input should be blocked
- requests should be traceable in logs

Core stack:

- FastAPI
- Ollama (`llama3` or `mistral`)
- Redis
- `language_tool_python`

## Architecture

Main components:

- `app/main.py`: FastAPI app, CORS, request tracing middleware, dependency warmup
- `app/api/routes.py`: HTTP endpoints, orchestration, readiness checks
- `app/services/ai_rewriter.py`: Ollama prompt generation, parsing, output quality gate
- `app/services/grammar_service.py`: grammar correction and warmup
- `app/services/guardrails.py`: validation and HR language guardrails
- `app/services/cache_service.py`: Redis cache read/write and compatibility checks
- `app/services/rate_limiter.py`: Redis-backed per-IP rate limiting
- `app/services/fallback_rewriter.py`: deterministic fallback rewrites
- `app/services/system_health.py`: readiness status for dependencies
- `app/core/redis_client.py`: shared Redis connection and health ping
- `app/utils/hash_utils.py`: stable hash and versioned cache key generation
- `app/utils/logger.py`: rotating audit logger with hashed payload fields
- `app/models/request_models.py`: request and response models

Request flow:

1. Validate input length and content.
2. Enforce prompt guardrails.
3. Rate-limit by client IP.
4. Build a versioned cache key from normalized input + model/prompt settings.
5. Load a cached suggestion pool from Redis if available.
6. If cache miss, grammar-correct input and generate a suggestion pool through Ollama.
7. Reject malformed or low-quality model output and retry automatically.
8. Fall back to deterministic local rewrites if the model still fails.
9. Return a non-overlapping batch of suggestions for the current `attempt`.
10. Log a structured audit event with request tracing metadata.

## Folder Structure

```text
text-improver-api/
├── app/
│   ├── api/
│   │   └── routes.py
│   ├── core/
│   │   └── redis_client.py
│   ├── models/
│   │   └── request_models.py
│   ├── services/
│   │   ├── ai_rewriter.py
│   │   ├── cache_service.py
│   │   ├── fallback_rewriter.py
│   │   ├── grammar_service.py
│   │   ├── guardrails.py
│   │   ├── rate_limiter.py
│   │   └── system_health.py
│   ├── utils/
│   │   ├── hash_utils.py
│   │   └── logger.py
│   ├── config.py
│   ├── main.py
│   └── test_ui.html
├── tests/
│   ├── test_api.py
│   └── test_services.py
├── requirements.txt
├── README.md
└── audit.log
```

## Local Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install and start Redis

macOS with Homebrew:

```bash
brew install redis
brew services start redis
```

Foreground mode:

```bash
redis-server
```

### 4. Install and run Ollama

Pull a local model:

```bash
ollama pull llama3
```

or:

```bash
ollama pull mistral
```

Start the Ollama daemon:

```bash
ollama serve
```

### 5. Run the API

Development:

```bash
uvicorn app.main:app --reload
```

Production-style local run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### 6. Run tests

```bash
python -m unittest discover -s tests -v
```

## Endpoints

- `GET /health`
  - liveness endpoint
- `GET /ready`
  - readiness endpoint
  - returns `503` when required dependencies are unavailable
- `POST /improve-text`
  - main rewrite endpoint

Swagger UI:

- `http://127.0.0.1:8000/docs`

## Request and Response Contract

### Request

```json
{
  "text": "I am writing to request leave for Monday and Tuesday.",
  "attempt": 0
}
```

### Response

```json
{
  "original": "I am writing to request leave for Monday and Tuesday.",
  "improved_input": "I am writing to request leave for Monday and Tuesday.",
  "attempt": 0,
  "selected_index": 0,
  "selected_suggestion": "I would like to formally communicate that I am writing to request leave for Monday and Tuesday.",
  "suggestions": [
    "I would like to formally communicate that I am writing to request leave for Monday and Tuesday.",
    "Please note that I am writing to request leave for Monday and Tuesday.",
    "I am writing to inform you that I am writing to request leave for Monday and Tuesday.",
    "This message is to respectfully state that I am writing to request leave for Monday and Tuesday.",
    "I would like to share that I am writing to request leave for Monday and Tuesday."
  ],
  "attempt_metadata": {
    "batch_size": 5,
    "pool_size": 10,
    "batch_start": 0,
    "next_attempt": 1,
    "wrapped": false
  },
  "cached": false,
  "latency_ms": 120
}
```

## Suggestions and Attempts

The API uses two levels of suggestion storage:

- visible batch size: `5`
- cached suggestion pool size: `10`

Behavior:

- `attempt = 0` returns pool items `1-5`
- `attempt = 1` returns pool items `6-10`
- next attempts wrap after all batches are exhausted

This is exposed in `attempt_metadata`:

- `batch_size`: number of suggestions in the current response
- `pool_size`: total cached suggestions for the input
- `batch_start`: zero-based starting index inside the pool
- `next_attempt`: next attempt value to request
- `wrapped`: whether the attempt cycle has wrapped to an earlier batch

## Caching

Redis caching is implemented for rewrite pools.

Current cache strategy:

- cache key is versioned
- cache key includes:
  - cache version
  - model name
  - prompt version
  - batch size
  - pool size
  - normalized text hash

Example key shape:

```text
rewrite:rewrite_v1:llama3:hr_prompt_v1:batch5:pool10:<sha256>
```

Cached payload includes:

- `improved_input`
- `suggestion_pool`
- `cache_metadata`

Legacy cache payloads without metadata are treated as incompatible and regenerated.

## Rate Limiting

Redis-backed per-IP rate limiting is enabled.

Configuration:

- `RATE_LIMIT`
- `RATE_WINDOW`

In production mode, Redis can be required so rate limiting fails closed instead of silently disabling itself.

## Production Behavior

Production-oriented hardening currently included:

- readiness endpoint at `GET /ready`
- request tracing with `x-request-id`
- response timing header `x-process-time-ms`
- rotating audit logs
- hashed audit payload fields instead of raw text
- versioned cache keys
- incompatible cache payload rejection
- configurable fail-closed Redis dependency mode
- startup grammar service warmup
- stricter model timeout
- low-quality Ollama output rejection with automatic retries

Recommended environment for production:

```bash
export ENVIRONMENT=production
export REQUIRE_REDIS=true
export REQUIRE_LANGUAGE_TOOL=false
export WARM_DEPENDENCIES_ON_STARTUP=true
export MODEL_TIMEOUT=8
```

Recommended startup:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

## Environment Variables

Common settings:

```bash
export MODEL_NAME=llama3
export OLLAMA_URL=http://localhost:11434/api/generate
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export CACHE_TTL=3600
export RATE_LIMIT=30
export RATE_WINDOW=60
export CACHE_VERSION=rewrite_v1
export PROMPT_VERSION=hr_prompt_v1
export ENVIRONMENT=production
export REQUIRE_REDIS=true
export WARM_DEPENDENCIES_ON_STARTUP=true
```

## Audit Logging

Audit logging is enabled for each request.

Current behavior:

- logs are written through a rotating file handler
- raw request/response text is not written directly
- hashed fields are logged for:
  - original input
  - grammar-corrected input
  - selected suggestion
- `request_id`, latency, and cache status are included

## Quality Gate

Ollama output is not accepted blindly.

Before suggestions are returned or cached, the backend rejects outputs that are:

- too short
- too few in number
- malformed
- label-like leftovers such as `Rewrite 1`
- punctuation-only fragments
- duplicate or near-empty suggestions

If the output fails quality checks, the API retries the model. If retries still fail, it falls back to deterministic local rewrites.

## Testing

Current automated coverage includes:

- route behavior
- readiness behavior
- cache compatibility
- cache key versioning
- rate limiting
- guardrails
- parser normalization
- malformed output cleanup
- low-quality model retry behavior
- fallback rotation

Run:

```bash
python -m unittest discover -s tests -v
```

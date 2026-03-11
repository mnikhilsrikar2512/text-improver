# AI Text Improver API

FastAPI service for HR-safe text rewriting using a local Ollama model, Redis-backed caching and rate limiting, grammar correction, audit logging, attempt-based suggestion pools, and feedback-driven learning from accepted and rejected suggestions.

## Overview

This API is designed for integration into internal HR and workflow systems where:

- no external API keys are allowed
- rewrites must stay on local infrastructure
- repeated requests should be cached
- retry attempts should return a fresh batch of suggestions
- accepted suggestions should influence future phrasing for the same input
- rejected suggestions should be filtered or demoted on later attempts
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
- `app/services/feedback_service.py`: accepted/rejected suggestion memory and reranking
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
6. Load the feedback profile for the same normalized input.
7. If cache miss or stale feedback version, grammar-correct input and generate a suggestion pool through Ollama.
8. Reject malformed or low-quality model output and retry automatically.
9. Fall back to deterministic local rewrites if the model still fails.
10. Rerank suggestions using accepted and rejected user feedback.
11. Return a non-overlapping batch of suggestions for the current `attempt`.
12. Log a structured audit event with request tracing metadata.

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
│   │   ├── feedback_service.py
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
- `POST /feedback`
  - records accepted and rejected suggestions for the same input

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
  "selected_suggestion": "I would like to request leave for Monday and Tuesday.",
  "suggestions": [
    "I would like to request leave for Monday and Tuesday.",
    "Please consider this my leave request for Monday and Tuesday.",
    "I am requesting leave for Monday and Tuesday."
  ],
  "attempt_metadata": {
    "batch_size": 3,
    "pool_size": 12,
    "batch_start": 0,
    "next_attempt": 1,
    "wrapped": false
  },
  "cached": false,
  "latency_ms": 120
}
```

### Feedback Request

```json
{
  "text": "I am writing to request leave for Monday and Tuesday.",
  "accepted_suggestion": "I would like to request leave for Monday and Tuesday.",
  "rejected_suggestions": [
    "Please consider this my leave request for Monday and Tuesday.",
    "I am requesting leave for Monday and Tuesday."
  ]
}
```

### Feedback Response

```json
{
  "status": "recorded",
  "learned_preferences": {
    "accepted": 1,
    "rejected": 2,
    "version": 1
  }
}
```

## Suggestions and Attempts

The API uses two levels of suggestion storage:

- visible batch size: `3`
- cached suggestion pool size: `12`

Behavior:

- `attempt = 0` returns pool items `1-3`
- `attempt = 1` returns pool items `4-6`
- `attempt = 2` returns pool items `7-9`
- `attempt = 3` returns pool items `10-12`
- next attempts wrap after all batches are exhausted

This is exposed in `attempt_metadata`:

- `batch_size`: number of suggestions in the current response
- `pool_size`: total cached suggestions for the input
- `batch_start`: zero-based starting index inside the pool
- `next_attempt`: next attempt value to request
- `wrapped`: whether the attempt cycle has wrapped to an earlier batch

## Feedback Learning

The API now learns per normalized input.

Behavior:

- the UI or client sends accepted and rejected suggestions to `POST /feedback`
- accepted suggestions are stored as preferred examples
- rejected suggestions are stored as phrases to avoid
- the feedback profile is passed into Ollama prompt generation
- cached suggestion pools are invalidated when the feedback profile changes
- future responses are reranked so accepted-style phrasing rises and rejected-style phrasing is filtered or demoted

This keeps the system from returning the same cached pool unchanged after the user has already shown a preference.

## Caching

Redis caching is implemented for rewrite pools, and feedback is stored separately.

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
rewrite:rewrite_v1:llama3:hr_prompt_v1:batch3:pool12:<sha256>
```

Cached payload includes:

- `improved_input`
- `suggestion_pool`
- `cache_metadata`

`cache_metadata` also includes a `feedback_version`. If the feedback profile changes because the user accepted or rejected suggestions, the old cached pool is treated as stale and the API regenerates a new pool.

Feedback storage uses a separate Redis key based on the normalized input hash and stores:

- accepted examples
- rejected examples
- accepted token counts
- rejected token counts
- feedback version

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
export FEEDBACK_TTL=2592000
export RATE_LIMIT=30
export RATE_WINDOW=60
export CACHE_VERSION=rewrite_v1
export PROMPT_VERSION=hr_prompt_v1
export ENVIRONMENT=production
export REQUIRE_REDIS=true
export WARM_DEPENDENCIES_ON_STARTUP=true
export SUGGESTION_COUNT=3
export SUGGESTION_POOL_SIZE=12
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

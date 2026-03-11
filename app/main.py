import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import ALLOWED_ORIGINS, API_TITLE, API_VERSION, WARM_DEPENDENCIES_ON_STARTUP
from app.services.grammar_service import warm_grammar_service

app = FastAPI(title=API_TITLE, version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-process-time-ms"] = str(int((time.perf_counter() - start) * 1000))
    return response


@app.on_event("startup")
def warm_dependencies():
    if WARM_DEPENDENCIES_ON_STARTUP:
        warm_grammar_service()

app.include_router(router)

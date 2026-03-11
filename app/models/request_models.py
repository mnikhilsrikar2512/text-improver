from pydantic import BaseModel, Field

from app.config import MAX_ATTEMPTS


class ImproveRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Free-form text to improve")
    attempt: int = Field(
        default=0,
        ge=0,
        le=MAX_ATTEMPTS,
        description="Zero-based retry counter used to rotate suggestion variations",
    )


class AttemptMetadata(BaseModel):
    batch_size: int
    pool_size: int
    batch_start: int
    next_attempt: int
    wrapped: bool


class ImproveResponse(BaseModel):
    original: str
    improved_input: str
    attempt: int
    selected_index: int
    selected_suggestion: str
    suggestions: list[str]
    attempt_metadata: AttemptMetadata
    cached: bool
    latency_ms: int


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, str]

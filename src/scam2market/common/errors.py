from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel


class ErrorCode(StrEnum):
    source_unavailable = "SOURCE_UNAVAILABLE"
    source_rate_limited = "SOURCE_RATE_LIMITED"
    event_schema_invalid = "EVENT_SCHEMA_INVALID"
    event_duplicate = "EVENT_DUPLICATE"
    event_too_late = "EVENT_TOO_LATE"
    feature_computation_failed = "FEATURE_COMPUTATION_FAILED"
    model_unavailable = "MODEL_UNAVAILABLE"
    model_schema_mismatch = "MODEL_SCHEMA_MISMATCH"
    graph_unavailable = "GRAPH_UNAVAILABLE"
    retrieval_unavailable = "RETRIEVAL_UNAVAILABLE"
    replay_state_invalid = "REPLAY_STATE_INVALID"
    internal_error = "INTERNAL_ERROR"


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = {}
    correlation_id: str | None = None


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                correlation_id=getattr(request.state, "correlation_id", None),
            ).model_dump(mode="json"),
        )

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class InvalidateRequest(BaseModel):
    """Optional body for POST /kbs/{kb_id}/invalidate — used for logging/tracing only."""

    document_id: str | None = None


class QueryRequest(BaseModel):
    question: str
    save: bool = False

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        if len(stripped) > 8000:
            raise ValueError("question must be 8000 characters or fewer")
        return stripped


class QueryResponse(BaseModel):
    answer: str
    citations: list[Any] = []
    tokens_used: int = 0


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: str
    azurite: str
    detail: str | None = None

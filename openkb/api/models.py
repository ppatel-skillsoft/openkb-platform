from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared validators (mirror _coerce_model / _coerce_language in cli.py)
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\n\r\t]")
_KB_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")


def _coerce_model(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if len(v) > 100:
        raise ValueError("model must be 100 characters or fewer")
    if _CONTROL_CHARS.search(v):
        raise ValueError("model must not contain newline, carriage-return, or tab characters")
    return v or None


def _coerce_language(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if len(v) > 50:
        raise ValueError("language must be 50 characters or fewer")
    if _CONTROL_CHARS.search(v):
        raise ValueError("language must not contain newline, carriage-return, or tab characters")
    return v or None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class KBInitRequest(BaseModel):
    kb_name: str
    model: str | None = None
    language: str | None = None

    @field_validator("kb_name")
    @classmethod
    def validate_kb_name(cls, v: str) -> str:
        if not _KB_NAME_RE.match(v):
            raise ValueError(
                "kb_name must be 1-64 lowercase alphanumeric characters, "
                "hyphens, or underscores, and must start and end with a letter or digit"
            )
        return v

    @field_validator("model", mode="before")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        return _coerce_model(v)

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, v: str | None) -> str | None:
        return _coerce_language(v)


class KBAddRequest(BaseModel):
    kb_name: str
    source: str

    @field_validator("kb_name")
    @classmethod
    def validate_kb_name(cls, v: str) -> str:
        if not _KB_NAME_RE.match(v):
            raise ValueError("Invalid kb_name format")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("source must not be blank")
        return v


class KBQueryRequest(BaseModel):
    kb_name: str
    question: str
    save: bool = False

    @field_validator("kb_name")
    @classmethod
    def validate_kb_name(cls, v: str) -> str:
        if not _KB_NAME_RE.match(v):
            raise ValueError("Invalid kb_name format")
        return v

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class KBInitResponse(BaseModel):
    kb_name: str
    status: Literal["created", "exists"]
    message: str


class KBAddResponse(BaseModel):
    status: Literal["added", "skipped", "failed"]
    doc_name: str | None = None
    message: str


class KBQueryResponse(BaseModel):
    answer: str
    saved_to: str | None = None


class DocumentItem(BaseModel):
    name: str
    doc_name: str
    type: str


class KBListResponse(BaseModel):
    documents: list[DocumentItem]
    summaries: list[str]
    concepts: list[str]
    entities: list[str]
    reports: list[str]


class KBStatusResponse(BaseModel):
    kb_name: str
    total_indexed: int
    last_compile: str | None = None
    last_lint: str | None = None
    directory_counts: dict[str, int]


class ErrorResponse(BaseModel):
    detail: str

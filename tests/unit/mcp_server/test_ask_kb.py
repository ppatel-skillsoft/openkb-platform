from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mcp_server.exceptions import GeneratorAPIError, KBNotFoundError, KBNotReadyError
from mcp_server.tools.ask_kb import (
    KBAnswer,
    _validate_kb_id,
    _validate_question,
    ask_kb,
)

logger = logging.getLogger(__name__)

_VALID_KB_ID = "12345678-1234-4234-8234-123456789012"
_VALID_QUESTION = "What is the main topic of this knowledge base?"


# ── Validation tests ──────────────────────────────────────────────────────────


def test_validate_kb_id_valid() -> None:
    _validate_kb_id(_VALID_KB_ID)  # should not raise


def test_validate_kb_id_non_uuid() -> None:
    with pytest.raises(ValueError, match="UUID"):
        _validate_kb_id("not-a-uuid")


def test_validate_kb_id_uuid_v1() -> None:
    with pytest.raises(ValueError):
        _validate_kb_id("550e8400-e29b-11d4-a716-446655440000")  # v1 UUID


def test_validate_question_valid() -> None:
    result = _validate_question("  hello?  ")
    assert result == "hello?"


def test_validate_question_blank() -> None:
    with pytest.raises(ValueError, match="blank"):
        _validate_question("   ")


def test_validate_question_too_long() -> None:
    with pytest.raises(ValueError, match="8000"):
        _validate_question("x" * 8001)


# ── ask_kb happy path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_kb_returns_kb_answer() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "answer": "Marketing focuses on brand awareness.",
        "citations": [{"page": "brand-overview"}],
        "tokens_used": 150,
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    ctx = MagicMock()
    ctx.lifespan_context = {"http_client": mock_client}

    result = await ask_kb(_VALID_KB_ID, _VALID_QUESTION, ctx)

    assert isinstance(result, KBAnswer)
    assert result.answer == "Marketing focuses on brand awareness."
    assert result.citations == [{"page": "brand-overview"}]
    assert result.tokens_used == 150
    assert result.kb_id == _VALID_KB_ID
    mock_client.post.assert_awaited_once_with(
        f"/kbs/{_VALID_KB_ID}/query",
        json={"question": _VALID_QUESTION},
    )


# ── ask_kb error mapping ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_kb_404_raises_kb_not_found() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.is_success = False
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    ctx = MagicMock()
    ctx.lifespan_context = {"http_client": mock_client}

    with pytest.raises(KBNotFoundError) as exc_info:
        await ask_kb(_VALID_KB_ID, _VALID_QUESTION, ctx)
    assert exc_info.value.kb_id == _VALID_KB_ID


@pytest.mark.asyncio
async def test_ask_kb_409_raises_kb_not_ready() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.is_success = False
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    ctx = MagicMock()
    ctx.lifespan_context = {"http_client": mock_client}

    with pytest.raises(KBNotReadyError) as exc_info:
        await ask_kb(_VALID_KB_ID, _VALID_QUESTION, ctx)
    assert exc_info.value.kb_id == _VALID_KB_ID


@pytest.mark.asyncio
async def test_ask_kb_timeout_raises_generator_api_error() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("timed out")

    ctx = MagicMock()
    ctx.lifespan_context = {"http_client": mock_client}

    with pytest.raises(GeneratorAPIError, match="timed out"):
        await ask_kb(_VALID_KB_ID, _VALID_QUESTION, ctx)


@pytest.mark.asyncio
async def test_ask_kb_5xx_raises_generator_api_error() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.is_success = False
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_resp

    ctx = MagicMock()
    ctx.lifespan_context = {"http_client": mock_client}

    with pytest.raises(GeneratorAPIError) as exc_info:
        await ask_kb(_VALID_KB_ID, _VALID_QUESTION, ctx)
    assert exc_info.value.status_code == 502

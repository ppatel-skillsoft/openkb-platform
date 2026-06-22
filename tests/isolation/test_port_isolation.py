"""FR-009, FR-010, FR-011 — Port isolation for concurrent query sidecars.

The generator-api spawns a fresh sidecar subprocess for each query request,
allocating a new OS-chosen port per sidecar. Concurrent queries to different
KBs must return responses containing only content from their own KB with no
cross-contamination.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.isolation.conftest import IsolationFixtures
from tests.isolation.helpers.process_helpers import (
    assert_generator_healthy,
    query_kb,
)


@pytest.mark.asyncio
async def test_generator_api_is_healthy(isolation_fixtures: IsolationFixtures) -> None:
    """FR-009: generator-api /health endpoint must report ok."""
    await assert_generator_healthy(isolation_fixtures.generator_api_url)


@pytest.mark.asyncio
async def test_concurrent_queries_return_correct_content(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-010: Concurrent queries to KB-A and KB-B must return content from their
    respective KBs with no cross-contamination between sidecars."""
    fx = isolation_fixtures

    # Fire both queries concurrently — each spawns its own sidecar on a unique port
    resp_a, resp_b = await asyncio.gather(
        query_kb(
            fx.generator_api_url,
            fx.kb_a_id,
            "What is the Hertzsprung-Russell diagram?",
        ),
        query_kb(
            fx.generator_api_url,
            fx.kb_b_id,
            "What is the role of chloroplasts in photosynthesis?",
        ),
    )

    answer_a = resp_a.get("answer", "").lower()
    answer_b = resp_b.get("answer", "").lower()

    # KB-A response must contain at least one astronomy keyword
    astronomy_hit = any(kw in answer_a for kw in fx.kb_a_topic_keywords)
    assert astronomy_hit, (
        f"KB-A response does not contain any astronomy keywords. answer={answer_a!r}"
    )

    # KB-B response must contain at least one botany keyword
    botany_hit = any(kw in answer_b for kw in fx.kb_b_topic_keywords)
    assert botany_hit, (
        f"KB-B response does not contain any botany keywords. answer={answer_b!r}"
    )


@pytest.mark.asyncio
async def test_kb_a_response_has_no_botany_content(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-011: KB-A query response must not contain KB-B topic keywords."""
    fx = isolation_fixtures

    resp = await query_kb(
        fx.generator_api_url,
        fx.kb_a_id,
        "Tell me about stellar evolution.",
    )
    answer = resp.get("answer", "").lower()

    # Botany keywords must NOT appear in an astronomy response
    leakage = [kw for kw in fx.kb_b_topic_keywords if kw in answer]
    assert not leakage, (
        f"KB-A response contains KB-B keywords (cross-contamination): {leakage}. "
        f"answer={answer!r}"
    )

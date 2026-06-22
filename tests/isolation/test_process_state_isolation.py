"""FR-012, FR-013 — Process state isolation.

After a query completes, the sidecar subprocess spawned by generator-api
must be stopped (no orphan processes). Queries to two different KBs must
return responses with no cross-contamination of content.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.isolation.conftest import IsolationFixtures
from tests.isolation.helpers.process_helpers import query_kb


@pytest.mark.asyncio
async def test_kb_b_response_has_no_astronomy_content(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-012: KB-B query response must not contain KB-A topic keywords."""
    fx = isolation_fixtures

    resp = await query_kb(
        fx.generator_api_url,
        fx.kb_b_id,
        "Describe the process of photosynthesis.",
    )
    answer = resp.get("answer", "").lower()

    leakage = [kw for kw in fx.kb_a_topic_keywords if kw in answer]
    assert not leakage, (
        f"KB-B response contains KB-A keywords (cross-contamination): {leakage}. "
        f"answer={answer!r}"
    )


@pytest.mark.asyncio
async def test_sequential_queries_are_independent(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-013: Sequential queries to KB-A then KB-B must each return correct content.

    This guards against sidecar state leaking between consecutive requests when
    the generator-api reuses an internal cache or process incorrectly.
    """
    fx = isolation_fixtures

    resp_a = await query_kb(
        fx.generator_api_url,
        fx.kb_a_id,
        "What is a red giant star?",
    )
    resp_b = await query_kb(
        fx.generator_api_url,
        fx.kb_b_id,
        "How do stomata regulate gas exchange?",
    )

    answer_a = resp_a.get("answer", "").lower()
    answer_b = resp_b.get("answer", "").lower()

    # KB-A must have astronomy content
    assert any(kw in answer_a for kw in fx.kb_a_topic_keywords), (
        f"KB-A sequential response missing astronomy keywords. answer={answer_a!r}"
    )
    # KB-B must have botany content
    assert any(kw in answer_b for kw in fx.kb_b_topic_keywords), (
        f"KB-B sequential response missing botany keywords. answer={answer_b!r}"
    )

    # No cross-contamination
    botany_in_a = [kw for kw in fx.kb_b_topic_keywords if kw in answer_a]
    astro_in_b = [kw for kw in fx.kb_a_topic_keywords if kw in answer_b]

    assert not botany_in_a, (
        f"Botany keywords found in KB-A response (cross-contamination): {botany_in_a}"
    )
    assert not astro_in_b, (
        f"Astronomy keywords found in KB-B response (cross-contamination): {astro_in_b}"
    )

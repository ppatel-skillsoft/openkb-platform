"""FR-014, FR-015 — Sequential reuse safety.

After a KB-A query completes, a subsequent KB-B query via the same
generator-api instance must still return correct, non-contaminated content.
This ensures the generator-api does not cache or reuse sidecar state between
requests for different KBs.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.isolation.conftest import IsolationFixtures
from tests.isolation.helpers.process_helpers import query_kb


@pytest.mark.asyncio
async def test_kb_b_correct_after_kb_a_query(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-014: After a KB-A query, a KB-B query must return botany content."""
    fx = isolation_fixtures

    # First query: KB-A
    await query_kb(fx.generator_api_url, fx.kb_a_id, "Describe main sequence stars.")

    # Second query immediately after: KB-B
    resp_b = await query_kb(
        fx.generator_api_url,
        fx.kb_b_id,
        "Explain the Calvin cycle in the chloroplast.",
    )
    answer_b = resp_b.get("answer", "").lower()

    botany_hit = any(kw in answer_b for kw in fx.kb_b_topic_keywords)
    assert botany_hit, (
        f"KB-B response after KB-A query is missing botany keywords. answer={answer_b!r}"
    )

    astro_leakage = [kw for kw in fx.kb_a_topic_keywords if kw in answer_b]
    assert not astro_leakage, (
        f"KB-B response contains astronomy keywords after KB-A query: {astro_leakage}"
    )


@pytest.mark.asyncio
async def test_kb_a_correct_after_kb_b_query(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-015: After a KB-B query, a KB-A query must return astronomy content."""
    fx = isolation_fixtures

    # First query: KB-B
    await query_kb(fx.generator_api_url, fx.kb_b_id, "What is phloem?")

    # Second query: KB-A
    resp_a = await query_kb(
        fx.generator_api_url,
        fx.kb_a_id,
        "What is a planetary nebula?",
    )
    answer_a = resp_a.get("answer", "").lower()

    astro_hit = any(kw in answer_a for kw in fx.kb_a_topic_keywords)
    assert astro_hit, (
        f"KB-A response after KB-B query is missing astronomy keywords. answer={answer_a!r}"
    )

    botany_leakage = [kw for kw in fx.kb_b_topic_keywords if kw in answer_a]
    assert not botany_leakage, (
        f"KB-A response contains botany keywords after KB-B query: {botany_leakage}"
    )

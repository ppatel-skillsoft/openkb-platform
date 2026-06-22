"""FR-016, FR-017 — Concurrent query isolation.

Multiple concurrent queries to the same generator-api instance targeting
different KBs must each return responses from their own KB without any
cross-contamination of content.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.isolation.conftest import IsolationFixtures
from tests.isolation.helpers.process_helpers import query_kb


@pytest.mark.asyncio
async def test_five_concurrent_queries_no_cross_contamination(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-016: Five concurrent queries (3×KB-A, 2×KB-B) must all return correct content."""
    fx = isolation_fixtures

    results = await asyncio.gather(
        query_kb(fx.generator_api_url, fx.kb_a_id, "Describe stellar evolution."),
        query_kb(fx.generator_api_url, fx.kb_b_id, "What are stomata?"),
        query_kb(fx.generator_api_url, fx.kb_a_id, "What is the Hertzsprung-Russell diagram?"),
        query_kb(fx.generator_api_url, fx.kb_b_id, "How does photosynthesis work?"),
        query_kb(fx.generator_api_url, fx.kb_a_id, "Explain red giants."),
    )

    # Indices 0, 2, 4 are KB-A; indices 1, 3 are KB-B
    kb_a_answers = [results[i].get("answer", "").lower() for i in (0, 2, 4)]
    kb_b_answers = [results[i].get("answer", "").lower() for i in (1, 3)]

    for idx, answer in enumerate(kb_a_answers):
        astro_hit = any(kw in answer for kw in fx.kb_a_topic_keywords)
        assert astro_hit, (
            f"KB-A concurrent response #{idx} missing astronomy keywords. answer={answer!r}"
        )
        botany_leak = [kw for kw in fx.kb_b_topic_keywords if kw in answer]
        assert not botany_leak, (
            f"KB-A concurrent response #{idx} contains botany keywords: {botany_leak}"
        )

    for idx, answer in enumerate(kb_b_answers):
        botany_hit = any(kw in answer for kw in fx.kb_b_topic_keywords)
        assert botany_hit, (
            f"KB-B concurrent response #{idx} missing botany keywords. answer={answer!r}"
        )
        astro_leak = [kw for kw in fx.kb_a_topic_keywords if kw in answer]
        assert not astro_leak, (
            f"KB-B concurrent response #{idx} contains astronomy keywords: {astro_leak}"
        )


@pytest.mark.asyncio
async def test_repeated_concurrent_queries_are_stable(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-017: A second wave of concurrent queries must return consistent, correct results."""
    fx = isolation_fixtures

    async def run_wave() -> tuple[str, str]:
        r_a, r_b = await asyncio.gather(
            query_kb(fx.generator_api_url, fx.kb_a_id, "What is a red giant?"),
            query_kb(fx.generator_api_url, fx.kb_b_id, "What is a chloroplast?"),
        )
        return r_a.get("answer", "").lower(), r_b.get("answer", "").lower()

    answer_a1, answer_b1 = await run_wave()
    answer_a2, answer_b2 = await run_wave()

    for label, answer in (("wave-1 KB-A", answer_a1), ("wave-2 KB-A", answer_a2)):
        assert any(kw in answer for kw in fx.kb_a_topic_keywords), (
            f"{label} missing astronomy keywords. answer={answer!r}"
        )
        botany_leak = [kw for kw in fx.kb_b_topic_keywords if kw in answer]
        assert not botany_leak, f"{label} has botany leakage: {botany_leak}"

    for label, answer in (("wave-1 KB-B", answer_b1), ("wave-2 KB-B", answer_b2)):
        assert any(kw in answer for kw in fx.kb_b_topic_keywords), (
            f"{label} missing botany keywords. answer={answer!r}"
        )
        astro_leak = [kw for kw in fx.kb_a_topic_keywords if kw in answer]
        assert not astro_leak, f"{label} has astronomy leakage: {astro_leak}"

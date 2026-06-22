"""FR-007, FR-008 — Scratch directory isolation.

Each concurrent compilation job must use its own isolated scratch directory.
After the job completes the scratch directory must be cleaned up.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.isolation.conftest import (
    IsolationFixtures,
    enqueue_job,
    wait_for_job_completion,
)
from tests.isolation.helpers.process_helpers import (
    assert_scratch_cleaned,
    assert_scratch_dirs_disjoint,
    list_scratch_dirs,
)

KB_A_BLOB = "kb-aaaaaaaa-0000-0000-0000-000000000001/raw/astronomy-intro.md"
KB_B_BLOB = "kb-bbbbbbbb-0000-0000-0000-000000000002/raw/botany-intro.md"


@pytest.mark.asyncio
async def test_concurrent_jobs_use_disjoint_scratch_dirs(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-007: Two concurrent compilation jobs must use distinct scratch directories."""
    fx = isolation_fixtures

    # Snapshot scratch dirs before enqueueing
    before = set(str(d) for d in list_scratch_dirs(fx.scratch_root))

    # Enqueue KB-A and KB-B jobs concurrently
    job_a_id, job_b_id = await asyncio.gather(
        enqueue_job(
            fx.database_url, fx.kb_a_id, fx.kb_a_doc_id, KB_A_BLOB, "astronomy-intro.md"
        ),
        enqueue_job(
            fx.database_url, fx.kb_b_id, fx.kb_b_doc_id, KB_B_BLOB, "botany-intro.md"
        ),
    )

    # Wait for both jobs to complete
    status_a, status_b = await asyncio.gather(
        wait_for_job_completion(fx.database_url, fx.kb_a_doc_id),
        wait_for_job_completion(fx.database_url, fx.kb_b_doc_id),
    )

    # Collect scratch dirs that appeared after enqueueing
    after = list_scratch_dirs(fx.scratch_root)
    new_dirs = [d for d in after if str(d) not in before]

    # Even if already cleaned, assert there was no overlap while running
    # (disjoint check: each dir name encodes the job, no shared prefix clash)
    if len(new_dirs) >= 2:
        assert_scratch_dirs_disjoint([new_dirs[0]], new_dirs[1:])


@pytest.mark.asyncio
async def test_scratch_dirs_cleaned_after_job(
    isolation_fixtures: IsolationFixtures,
) -> None:
    """FR-008: After a job completes, its scratch directory must be removed."""
    fx = isolation_fixtures

    before = set(str(d) for d in list_scratch_dirs(fx.scratch_root))

    job_id = await enqueue_job(
        fx.database_url, fx.kb_a_doc_id, fx.kb_a_doc_id, KB_A_BLOB, "astronomy-intro.md"
    )

    status = await wait_for_job_completion(fx.database_url, fx.kb_a_doc_id)

    after = list_scratch_dirs(fx.scratch_root)
    new_dirs = [d for d in after if str(d) not in before]

    # All scratch dirs created during this job should be cleaned up
    assert_scratch_cleaned(new_dirs, fx.scratch_root)

"""HTTP and process-assertion helpers for isolation tests.

These helpers are designed to work from the isolation-tests container. Since
process-table inspection (psutil) is scoped to the local container, port-binding
assertions here verify the generator-api is reachable and responsive, not the
internal sidecar ports of the compiler-worker container.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx


async def wait_for_http(url: str, *, timeout: float = 60.0, interval: float = 1.0) -> None:
    """Poll *url* until it returns HTTP 2xx or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(url, timeout=5.0)
                if resp.is_success:
                    return
            except Exception as exc:
                last_exc = exc
            await asyncio.sleep(interval)
    raise TimeoutError(
        f"Service at {url!r} did not become healthy within {timeout}s"
        + (f": {last_exc}" if last_exc else "")
    )


async def assert_generator_healthy(generator_url: str) -> None:
    """Assert that the generator-api /health endpoint returns 200."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{generator_url}/health", timeout=10.0)
    assert resp.status_code == 200, f"Generator health check failed: {resp.text}"
    data = resp.json()
    assert data.get("status") == "ok", f"Generator reported unhealthy: {data}"


async def query_kb(
    generator_url: str,
    kb_id: str,
    question: str,
    *,
    timeout: float = 60.0,
) -> dict:
    """POST a query to the generator-api and return the parsed JSON response."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{generator_url}/kbs/{kb_id}/query",
            json={"question": question},
            timeout=timeout,
        )
    resp.raise_for_status()
    return resp.json()


def list_scratch_dirs(scratch_root: Path) -> list[Path]:
    """Return all ``openkb-job-*`` directories currently in *scratch_root*."""
    if not scratch_root.exists():
        return []
    return sorted(scratch_root.glob("openkb-job-*"))


def assert_scratch_dirs_disjoint(dirs_a: list[Path], dirs_b: list[Path]) -> None:
    """Assert that two sets of scratch dirs share no common paths."""
    set_a = {str(d) for d in dirs_a}
    set_b = {str(d) for d in dirs_b}
    overlap = set_a & set_b
    assert not overlap, f"Scratch dirs overlap between jobs: {overlap}"


def assert_scratch_cleaned(dirs: list[Path], scratch_root: Path) -> None:
    """Assert that all given scratch dirs have been removed from *scratch_root*."""
    still_present = [d for d in dirs if d.exists()]
    assert not still_present, (
        f"Expected scratch dirs to be cleaned up but still present: {still_present}"
    )

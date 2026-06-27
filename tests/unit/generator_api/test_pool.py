"""Unit tests for SidecarPool — failing stubs (T010) filled in during Phases 3–6."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from generator_api.config import Settings
from generator_api.pool import SidecarPool, _SidecarEntry
from generator_api.sidecar import SidecarProcess


def _make_settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
        "azure_storage_connection_string": "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;",
        "llm_api_key": "sk-test",
        **overrides,
    }
    return Settings(**base)


# ---------------------------------------------------------------------------
# Phase 3 — US1: get_or_start (T011, T012, T013)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_start_warm_cache_skips_start_entry() -> None:
    """Warm path: healthy entry in registry → _start_sidecar NOT called (T011)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    # Inject a healthy entry
    mock_proc = MagicMock(spec=SidecarProcess)
    mock_proc.is_healthy.return_value = True
    mock_proc._process = MagicMock()
    entry = _SidecarEntry(process=mock_proc, lock=asyncio.Lock())
    pool._registry["kb-1"] = entry

    with patch.object(pool, "_start_sidecar", new_callable=AsyncMock) as mock_start:
        result = await pool.get_or_start("kb-1", "test-kb", "kb-test")
        mock_start.assert_not_called()
    assert result is mock_proc


@pytest.mark.asyncio
async def test_get_or_start_cold_start_calls_start_sidecar() -> None:
    """Cold start: empty registry → _start_sidecar IS called (T012)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    async def fake_start(kb_id, kb_slug, container, entry):
        # Simulate a started process
        mock_proc = MagicMock(spec=SidecarProcess)
        mock_proc.is_healthy.return_value = True
        mock_proc._process = MagicMock()
        entry.process = mock_proc

    with patch.object(pool, "_start_sidecar", side_effect=fake_start) as mock_start:
        await pool.get_or_start("kb-new", "new-kb", "kb-new")
        mock_start.assert_called_once()
    assert "kb-new" in pool._registry


@pytest.mark.asyncio
async def test_get_or_start_concurrent_same_kb_starts_only_once() -> None:
    """Concurrent calls for the same KB → _start_sidecar called exactly once (T013)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    call_count = 0

    async def fake_start(kb_id, kb_slug, container, entry):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # simulate startup latency
        mock_proc = MagicMock(spec=SidecarProcess)
        mock_proc.is_healthy.return_value = True
        mock_proc._process = MagicMock()
        entry.process = mock_proc

    with patch.object(pool, "_start_sidecar", side_effect=fake_start):
        results = await asyncio.gather(
            pool.get_or_start("kb-concurrent", "concurrent-kb", "kb-c"),
            pool.get_or_start("kb-concurrent", "concurrent-kb", "kb-c"),
        )

    assert call_count == 1, f"Expected 1 start, got {call_count}"
    # Both callers should get the same process back
    assert results[0] is results[1]


# ---------------------------------------------------------------------------
# Phase 4 — US4: stop_kb + shutdown + crash detection (T021, T022, T023)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_kb_removes_entry_and_calls_stop_entry() -> None:
    """stop_kb removes the entry from registry (T021)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    mock_proc = MagicMock(spec=SidecarProcess)
    mock_proc.is_healthy.return_value = True
    mock_proc._process = MagicMock()
    entry = _SidecarEntry(process=mock_proc, lock=asyncio.Lock())
    pool._registry["kb-stop"] = entry

    with patch.object(pool, "_stop_entry", new_callable=AsyncMock) as mock_stop:
        await pool.stop_kb("kb-stop")
        mock_stop.assert_called_once_with("kb-stop", entry, reason="stop_kb")
    assert "kb-stop" not in pool._registry


@pytest.mark.asyncio
async def test_stop_kb_unknown_kb_is_noop() -> None:
    """stop_kb for unknown kb_id raises no exception (T021)."""
    settings = _make_settings()
    pool = SidecarPool(settings)
    await pool.stop_kb("non-existent-kb")  # should not raise


@pytest.mark.asyncio
async def test_shutdown_stops_all_entries() -> None:
    """shutdown calls _stop_entry for each entry and clears registry (T022)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    for i in range(2):
        mock_proc = MagicMock(spec=SidecarProcess)
        mock_proc._process = MagicMock()
        pool._registry[f"kb-{i}"] = _SidecarEntry(
            process=mock_proc, lock=asyncio.Lock()
        )

    with patch.object(pool, "_stop_entry", new_callable=AsyncMock) as mock_stop:
        await pool.shutdown()
        assert mock_stop.call_count == 2
    assert len(pool._registry) == 0


@pytest.mark.asyncio
async def test_crash_detection_triggers_restart() -> None:
    """Crashed sidecar (is_healthy=False after start) triggers restart (T023)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    # A process that was started but now shows as crashed
    crashed_proc = MagicMock(spec=SidecarProcess)
    crashed_proc.is_healthy.return_value = False
    crashed_proc._process = MagicMock()  # non-None = "was started, now crashed"
    entry = _SidecarEntry(process=crashed_proc, lock=asyncio.Lock())
    pool._registry["kb-crash"] = entry

    restart_called = False

    async def fake_start(kb_id, kb_slug, container, entry_arg):
        nonlocal restart_called
        restart_called = True
        fresh_proc = MagicMock(spec=SidecarProcess)
        fresh_proc.is_healthy.return_value = True
        fresh_proc._process = MagicMock()
        entry_arg.process = fresh_proc

    with (
        patch.object(pool, "_start_sidecar", side_effect=fake_start),
        patch.object(pool, "_stop_entry", new_callable=AsyncMock),
    ):
        await pool.get_or_start("kb-crash", "crash-kb", "kb-crash")

    assert restart_called, "Expected _start_sidecar to be called after crash detection"


# ---------------------------------------------------------------------------
# Phase 5 — US2: invalidate (T028)
# ---------------------------------------------------------------------------


def test_invalidate_marks_existing_entry_stale() -> None:
    """invalidate sets stale=True on an existing entry (T028a)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    mock_proc = MagicMock(spec=SidecarProcess)
    mock_proc._process = MagicMock()
    entry = _SidecarEntry(process=mock_proc, lock=asyncio.Lock())
    pool._registry["kb-inv"] = entry

    pool.invalidate("kb-inv")
    assert entry.stale is True


def test_invalidate_absent_kb_is_noop() -> None:
    """invalidate for a KB with no running sidecar is a no-op (T028b)."""
    settings = _make_settings()
    pool = SidecarPool(settings)
    pool.invalidate("non-existent")  # should not raise


@pytest.mark.asyncio
async def test_stale_entry_triggers_restart_on_next_get_or_start() -> None:
    """Stale entry triggers _start_sidecar on next get_or_start (T028c)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    stale_proc = MagicMock(spec=SidecarProcess)
    stale_proc.is_healthy.return_value = True
    stale_proc._process = MagicMock()
    entry = _SidecarEntry(process=stale_proc, lock=asyncio.Lock(), stale=True)
    pool._registry["kb-stale"] = entry

    async def fake_start(kb_id, kb_slug, container, entry_arg):
        fresh = MagicMock(spec=SidecarProcess)
        fresh.is_healthy.return_value = True
        fresh._process = MagicMock()
        entry_arg.process = fresh

    with (
        patch.object(pool, "_start_sidecar", side_effect=fake_start) as mock_start,
        patch.object(pool, "_stop_entry", new_callable=AsyncMock),
    ):
        await pool.get_or_start("kb-stale", "stale-kb", "kb-stale")
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 6 — US3: eviction (T035, T036)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_idle_removes_idle_entry() -> None:
    """Entry idle longer than TTL is stopped and removed (T035a)."""
    settings = _make_settings(sidecar_idle_ttl_seconds=10)
    pool = SidecarPool(settings)

    old_proc = MagicMock(spec=SidecarProcess)
    old_proc._process = MagicMock()
    entry = _SidecarEntry(
        process=old_proc,
        lock=asyncio.Lock(),
        last_used_at=time.monotonic() - 20,  # 20s idle > 10s TTL
    )
    pool._registry["kb-idle"] = entry

    with patch.object(pool, "_stop_entry", new_callable=AsyncMock) as mock_stop:
        await pool._evict_idle()
        mock_stop.assert_called_once()
    assert "kb-idle" not in pool._registry


@pytest.mark.asyncio
async def test_evict_idle_keeps_active_entry() -> None:
    """Entry used recently is NOT evicted (T035b)."""
    settings = _make_settings(sidecar_idle_ttl_seconds=1800)
    pool = SidecarPool(settings)

    active_proc = MagicMock(spec=SidecarProcess)
    active_proc._process = MagicMock()
    entry = _SidecarEntry(
        process=active_proc,
        lock=asyncio.Lock(),
        last_used_at=time.monotonic(),  # just used
    )
    pool._registry["kb-active"] = entry

    with patch.object(pool, "_stop_entry", new_callable=AsyncMock) as mock_stop:
        await pool._evict_idle()
        mock_stop.assert_not_called()
    assert "kb-active" in pool._registry


@pytest.mark.asyncio
async def test_evict_idle_removes_stale_entry_regardless_of_recency() -> None:
    """Stale entry is evicted even if recently used (T035c)."""
    settings = _make_settings(sidecar_idle_ttl_seconds=1800)
    pool = SidecarPool(settings)

    proc = MagicMock(spec=SidecarProcess)
    proc._process = MagicMock()
    entry = _SidecarEntry(
        process=proc,
        lock=asyncio.Lock(),
        stale=True,
        last_used_at=time.monotonic(),  # recently used but stale
    )
    pool._registry["kb-stale-evict"] = entry

    with patch.object(pool, "_stop_entry", new_callable=AsyncMock) as mock_stop:
        await pool._evict_idle()
        mock_stop.assert_called_once()
    assert "kb-stale-evict" not in pool._registry


@pytest.mark.asyncio
async def test_evict_idle_loop_exits_on_cancelled_error() -> None:
    """evict_idle_loop exits cleanly on CancelledError (T036)."""
    settings = _make_settings()
    pool = SidecarPool(settings)

    call_count = 0

    async def fake_sleep(secs):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError

    with (
        patch("generator_api.pool.asyncio.sleep", side_effect=fake_sleep),
        patch.object(pool, "_evict_idle", new_callable=AsyncMock),
    ):
        await pool.evict_idle_loop()  # should return, not hang

    assert call_count >= 1

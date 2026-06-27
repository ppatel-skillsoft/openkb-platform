# Research: Persistent KB Sidecar Pool

**Feature**: 010-persistent-kb-sidecar-pool
**Phase**: 0 — Research
**Date**: 2026-06-26

---

## R-001: Does `rebuild_index_md()` exist in `generator_api/blob.py`?

**Question**: The spec assumes `generator_api/blob.py::rebuild_index_md()` is "correct and
reusable as-is". Does it exist?

**Finding**: It does **not** exist in the current codebase. `generator_api/blob.py` contains only:
- `check_azurite(connection_string) -> str`
- `sync_wiki_tree(connection_string, container, kb_blob_prefix, scratch_dir) -> None`

The current `router.py` calls `sync_wiki_tree` but does **not** call any `rebuild_index_md`
function. Looking at the existing `openkb serve` subprocess contract — the sidecar receives a
`POST /kb/init` after startup with `{"kb_name": kb_slug}`, which presumably drives index
construction internally within `openkb-core`.

**Decision**: `rebuild_index_md()` is **not required as a separate step** in the new pool design.
The existing protocol (`sync_wiki_tree` → `sidecar.start` → `sidecar.init`) already covers the
complete startup sequence. The spec assumption is slightly inaccurate; the plan will not add a
`rebuild_index_md` function. If `openkb-core` changes require it in the future, it should be
added to `blob.py` at that time.

**Rationale**: Adding a non-existent function would create dead code or break the contract with
the `openkb serve` subprocess. The existing `init` call to the running sidecar serves the same
purpose at the sidecar level.

**Alternatives considered**: Adding a stub `rebuild_index_md()` to `blob.py` — rejected because
it would be unused dead code and add confusion.

---

## R-002: Per-KB `asyncio.Lock` in a pool dict — best practices

**Question**: What is the right pattern for maintaining a `dict[str, _SidecarEntry]` with
per-KB asyncio locks, given that the pool dict itself may be mutated concurrently?

**Finding**: The canonical asyncio pattern for per-key locking with a shared dictionary is:

1. Protect the *dictionary itself* with a single `asyncio.Lock` (the "registry lock") for
   all operations that insert or delete entries.
2. Store a *per-entry* `asyncio.Lock` inside each `_SidecarEntry` to serialise start/stop
   operations for that specific KB.
3. The per-entry lock must be acquired *outside* the registry lock to avoid lock inversion
   and deadlock: acquire registry lock → look up or create entry + entry lock → release registry
   lock → acquire entry lock → perform sidecar operation → release entry lock.

**Decision**:
- `SidecarPool._registry: dict[str, _SidecarEntry]` — the pool dict.
- `SidecarPool._registry_lock: asyncio.Lock` — protects inserts/deletes into `_registry`.
- `_SidecarEntry.lock: asyncio.Lock` — serialises start/stop for one KB.
- `get_or_start()` acquires `_registry_lock` briefly to get-or-create the entry, then releases
  it before acquiring `entry.lock` for the actual startup work.

**Rationale**: This two-lock pattern is well-established in asyncio pool implementations. The
narrow registry lock minimises contention; the per-entry lock ensures only one goroutine drives
any given KB's lifecycle at a time.

**Alternatives considered**:
- Single global lock — rejected: would serialize all KB lookups under load.
- `asyncio.Semaphore` per entry — rejected: more complex signalling needed for startup wait;
  Lock semantics are sufficient.

---

## R-003: Making `SidecarProcess.start()` asyncio-compatible (blocking I/O)

**Question**: `SidecarProcess.start()` uses `time.sleep` in a polling loop. The current code
runs it via `asyncio.to_thread`. Is this sufficient, or should we convert to async polling?

**Finding**: The current `router.py` already uses `await asyncio.to_thread(sidecar.start, ...)`
which offloads the blocking loop to a thread-pool executor. This is correct and sufficient.

However, with the pool, the sidecar startup is driven inside `get_or_start()` which runs in the
asyncio event loop. To preserve the `asyncio.to_thread` pattern, `SidecarPool.get_or_start()`
must itself use `await asyncio.to_thread(self._start_sidecar, ...)` for the blocking portion.

**Decision**: Keep `SidecarProcess.start()`, `init()`, and `teardown()` synchronous. Wrap all
calls to them in `asyncio.to_thread()` inside the pool. This avoids re-writing the sidecar
subprocess management and is consistent with the existing pattern in `router.py`.

**Rationale**: `asyncio.to_thread` is the idiomatic way to bridge sync blocking code into an
async context without converting the entire call chain. The overhead is negligible for an
operation that takes 5–30 seconds.

**Alternatives considered**:
- Converting `SidecarProcess.start()` to async with `asyncio.sleep` — possible but would
  require rewriting the health-poll loop and removing the `asyncio.to_thread` wrapping; higher
  risk for marginal gain.
- `loop.run_in_executor(None, ...)` — equivalent to `asyncio.to_thread`, just lower-level.

---

## R-004: Fire-and-forget HTTP call in `compiler_worker/job.py`

**Question**: `compiler_worker` runs as `asyncio.run(_async_run())`. `process_job` is already
`async`. What is the cleanest way to issue a fire-and-forget `POST /kbs/{kb_id}/invalidate`
without blocking job processing or propagating errors?

**Finding**: `process_job` in `compiler_worker/job.py` is already async. The correct pattern is:

```python
async with httpx.AsyncClient(timeout=5.0) as client:
    try:
        await client.post(
            f"{config.generator_api_url}/kbs/{kb_id}/invalidate",
            json={"document_id": str(document_id)},
        )
    except Exception:
        logger.warning("Failed to notify generator_api of invalidation for kb %s", kb_id)
```

The `await` here does not block job processing because it is called *after* the DB commit that
marks the document `complete`. Errors are caught broadly and logged at WARNING, never raised.

**Decision**: Use `httpx.AsyncClient` for the invalidation call. Add
`GENERATOR_API_URL` to `compiler_worker/config.py` (default `http://generator-api:8001`). The
call is placed immediately after the `logger.info("Job %s completed ...")` line in `job.py`.
On any exception (connection refused, timeout, HTTP error), log at WARNING and continue.

**Rationale**: `httpx` is already a dependency of the project (used in `generator_api/sidecar.py`
and present in `pyproject.toml`). Using `AsyncClient` within the existing async context is the
most natural fit.

**Alternatives considered**:
- `asyncio.create_task(...)` for true fire-and-forget (non-awaited) — rejected: if the job
  completes before the task fires, the event loop may be torn down before the call is sent.
  A simple `await` with error swallowing achieves the same semantic with less complexity.
- `requests` (sync) — rejected: would block the asyncio event loop.
- A queue / side-channel — rejected: over-engineered for a fire-and-forget notification.

---

## R-005: Background eviction task in FastAPI lifespan

**Question**: What is the canonical way to run a periodic background asyncio task tied to
FastAPI's lifespan (starts on startup, cancelled on shutdown)?

**Finding**: FastAPI's `@asynccontextmanager` lifespan yields exactly once. The correct pattern is:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    pool = SidecarPool(settings)
    eviction_task = asyncio.create_task(pool.evict_idle_loop())
    app.state.pool = pool
    try:
        yield
    finally:
        eviction_task.cancel()
        await pool.shutdown()
```

`evict_idle_loop()` is an infinite `while True: await asyncio.sleep(60); await _evict_idle()`
loop. Cancellation via `task.cancel()` raises `asyncio.CancelledError` inside the loop on the
next `await asyncio.sleep`.

**Decision**: `SidecarPool` exposes:
- `async def evict_idle_loop(self) -> None` — the long-running background coroutine.
- `async def shutdown(self) -> None` — stops all running sidecars gracefully.

The eviction task is created in `app.py::_lifespan()` and cancelled there on shutdown.
`pool.shutdown()` is always called in the `finally` block to ensure clean teardown even if the
eviction task fails.

**Rationale**: `asyncio.create_task` is the correct approach for background work in an async
context. Cancellation is cooperative via `asyncio.CancelledError`. Putting teardown in `finally`
guarantees it runs even on unhandled exceptions during lifespan yield.

**Alternatives considered**:
- `BackgroundTasks` (FastAPI) — rejected: designed for per-request background work, not
  long-lived service tasks.
- `apscheduler` library — rejected: external dependency; `asyncio.sleep` loop is sufficient.

---

## R-006: Dead process detection in the pool

**Question**: If `openkb serve` crashes between queries, how does the pool detect this?

**Finding**: `subprocess.Popen.poll()` returns `None` if the process is still running, or an
integer exit code if it has terminated. This is a non-blocking, synchronous check and safe to
call in the event loop without offloading to a thread.

**Decision**: Add `SidecarProcess.is_healthy() -> bool`:

```python
def is_healthy(self) -> bool:
    return self._process is not None and self._process.poll() is None
```

`SidecarPool.get_or_start()` calls `entry.process.is_healthy()` after acquiring the per-entry
lock. If `not is_healthy()`, the entry is treated as stale (same code path as an explicit
`invalidate`): teardown → delete scratch dir → re-sync → start fresh.

A new exception `SidecarCrashedError` is added to `exceptions.py` and logged at WARNING when
a crash is detected between queries.

**Rationale**: `poll()` is the standard library mechanism for non-blocking process status checks.
It is safe to call without a thread because it does not block.

**Alternatives considered**:
- Monitoring via `asyncio.subprocess` and awaiting exit — would require converting the subprocess
  to async; too large a change for this feature.
- A dedicated watchdog task per sidecar — over-engineered; on-demand detection at query time is
  sufficient since the use case (crash between queries) is rare.

---

## R-007: Per-KB scratch directory lifecycle

**Question**: The current design uses a per-request temporary directory (`/tmp/generator-scratch/{uuid}/`).
The pool design requires a persistent per-KB directory. How should this be managed?

**Finding**: The pool scratch directory must persist across queries so the sidecar process can
continue to serve from the already-synced wiki tree. The directory should be:
- Created on first sidecar start for a KB.
- Deleted on sidecar stop (any reason: eviction, invalidation, crash, shutdown).
- Re-created on next sidecar start after stop.

Path: `{settings.scratch_dir_root}/{kb_id}/kbs/` — matching the existing `router.py` sub-path
pattern (`scratch_dir / kb_slug`).

**Decision**: `SidecarPool` is responsible for creating and deleting the scratch directory as
part of `_start_entry()` and `_stop_entry()`. The path is computed as:
`settings.scratch_dir_root / str(kb_id)`. This replaces the per-request `uuid` segment with the
stable `kb_id` UUID, preserving the same depth.

On stop/eviction: `shutil.rmtree(scratch_dir, ignore_errors=True)`.
On start: `scratch_dir.mkdir(parents=True, exist_ok=True)` — `exist_ok=True` is safe because
the directory is empty after the previous rmtree.

**Rationale**: Using `kb_id` as the directory name provides deterministic, debuggable paths and
ensures isolation (FR-014 from spec).

**Alternatives considered**:
- Keeping temp dirs per-request inside the pool — rejected: would require re-syncing blobs on
  every query, defeating the purpose of the pool.
- A single shared scratch root without per-KB isolation — rejected: violates Constitution
  Principle IV (per-customer/per-KB isolation).

---

## R-008: Query timeout — 120 s vs. existing 300 s default

**Question**: The spec FR-009 says query timeout default is 120 s. The existing
`generator_request_timeout` in `config.py` defaults to 300 s. Which wins?

**Finding**: The spec FR-009 establishes 120 s as the default for this feature. The existing 300 s
value in `config.py` is a legacy of the per-request model where the full blob sync + start + query
all counted against the timeout. With the pool, only the query itself counts (warm sidecars have
no startup overhead).

**Decision**: Rename the setting in `config.py` from `generator_request_timeout` (300 s) to keep
the name but change the default to 120 s. Update the docstring to clarify it now covers query
time only (not startup time, which is covered by `sidecar_startup_timeout`). All existing
references to `settings.generator_request_timeout` in `router.py` and `app.py` remain valid.

**Rationale**: 300 s was originally padded to accommodate cold-start latency. With the pool, warm
queries should complete in < 2 s; a 120 s timeout provides ample headroom without allowing
runaway queries to block the event loop for 5 minutes.

**Alternatives considered**:
- Introducing a separate `sidecar_query_timeout` — possible but adds config proliferation; using
  the existing `generator_request_timeout` with an updated default is simpler.

---

## R-009: Pre-warming KBs on startup

**Question**: The architecture notes say "Pool startup in main.py lifespan: pre-warm all ready
KBs (query DB for complete docs)". Should pre-warming be synchronous (block lifespan yield)
or async (background)?

**Finding**: Pre-warming all ready KBs on startup could be slow (each sidecar takes 5–30 s to
start). Blocking the lifespan yield until all sidecars are ready would delay the service
becoming available and could cause health-check timeouts in container orchestration.

**Decision**: Pre-warming is **opt-in and best-effort**. If `GENERATOR_PREWARM_ON_STARTUP=true`
(default `false`), the pool schedules warm-up tasks via `asyncio.gather` in the background after
the lifespan yield (i.e., after the service is accepting requests). Startup failures for
individual KBs are logged at WARNING but do not prevent the service from starting. The first
query to an unwarmed KB triggers a cold start as normal.

**Rationale**: Container orchestration health checks (e.g., Kubernetes readiness probes) would
mark the pod as unready if startup takes 20+ seconds for 5 KBs. Background pre-warming keeps the
service available immediately.

**Alternatives considered**:
- Blocking pre-warm — rejected: too slow for any realistic deployment with > 2 KBs.
- Always pre-warming — rejected: most deployments will not need all KBs pre-warmed immediately,
  and the cold-start on first query is acceptable.

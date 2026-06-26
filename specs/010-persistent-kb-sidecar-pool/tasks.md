---

description: "Task list for feature 010: Persistent KB Sidecar Pool"

---

# Tasks: Persistent KB Sidecar Pool

**Feature**: 010-persistent-kb-sidecar-pool
**Input**: `specs/010-persistent-kb-sidecar-pool/` — plan.md, spec.md, data-model.md, research.md, contracts/, quickstart.md
**Approach**: TDD — tests written before or alongside each implementation task

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: Can run in parallel (independent files, no unresolved dependencies)
- **[US?]**: User story this task belongs to (US1–US4)
- Setup / Foundational phases: no [US?] label

---

## Phase 1: Setup (Shared Configuration & Models)

**Purpose**: Add all new config fields, exception types, and Pydantic models needed before any
pool logic can be written. All four tasks touch different files and are fully independent.

- [X] T001 [P] Add `sidecar_idle_ttl_seconds: int = 1800`, `sidecar_startup_timeout: int = 30`, and `prewarm_on_startup: bool = False` config fields; update `generator_request_timeout` default from 300 to 120 with updated docstring ("query time only; startup governed by sidecar_startup_timeout") in `generator_api/config.py`
- [X] T002 [P] Add `SidecarCrashedError(kb_id: str)` exception class to `generator_api/exceptions.py` with message `f"Sidecar for KB {kb_id} crashed unexpectedly"` and `self.kb_id = kb_id`
- [X] T003 [P] Add `InvalidateRequest(BaseModel)` Pydantic model with `document_id: str | None = None` field (used for logging/tracing only) to `generator_api/models.py`
- [X] T004 [P] Add `generator_api_url: str = "http://generator-api:8001"` field to `WorkerConfig` in `compiler_worker/config.py`, controlled by `GENERATOR_API_URL` env var

**Checkpoint**: All new types are importable — pool implementation can begin

---

## Phase 2: Foundational (SidecarProcess + Pool Scaffold)

**Purpose**: Extend `SidecarProcess` with pool-required attributes, scaffold `pool.py`, and
create test directories. These are blocking prerequisites for all user story phases.

- [X] T005 Add `last_used_at: float = time.monotonic()` instance attribute and `is_healthy(self) -> bool` method (returns `self._process is not None and self._process.poll() is None`) to `SidecarProcess` in `generator_api/sidecar.py`; ensure `is_healthy()` returns `False` before `start()` is called
- [X] T006 [P] Write unit tests for `SidecarProcess.is_healthy()` in `tests/unit/generator_api/test_sidecar.py`: assert returns `False` when process never started, `False` after process is killed (simulated with `poll()` returning non-None), `True` while process is alive (simulated with `poll()` returning `None`)
- [X] T007 [P] Create `tests/unit/generator_api/__init__.py` and `tests/integration/generator_api/__init__.py` (empty package init files to register new test packages)
- [X] T008 Create `tests/integration/generator_api/conftest.py` with a `test_app` TestClient fixture (wraps `generator_api` FastAPI app) and a `mock_pool` fixture that returns a `MagicMock` with `get_or_start`, `invalidate`, `update_last_used`, `shutdown` attributes; attach `mock_pool` to `app.state.pool` for route-level tests
- [X] T009 Create `generator_api/pool.py`: `from __future__ import annotations`, imports (`asyncio`, `dataclasses`, `logging`, `shutil`, `time`, `pathlib.Path`), `logger = logging.getLogger(__name__)`, `_SidecarEntry` dataclass with fields `process: SidecarProcess`, `lock: asyncio.Lock`, `stale: bool = False`, `last_used_at: float = dataclasses.field(default_factory=time.monotonic)`, and `SidecarPool.__init__(self, settings: Settings)` initialising `self._settings`, `self._registry: dict[str, _SidecarEntry] = {}`, `self._registry_lock = asyncio.Lock()`
- [X] T010 Write failing unit test stubs in `tests/unit/generator_api/test_pool.py` covering each public method: `get_or_start` (warm, cold, concurrent), `invalidate` (exists, missing), `stop_kb` (exists, missing), `shutdown` (all entries), `evict_idle_loop` / `_evict_idle` (idle evicted, active kept), crash-detection path — leave test bodies as `pytest.fail("not implemented")` so the suite fails red before implementation

**Checkpoint**: Foundation ready — all user story phases can proceed

---

## Phase 3: User Story 1 — Fast Repeated KB Queries (Priority: P1) 🎯 MVP

**Goal**: Pool serves warm sidecars directly; concurrent first-queries are serialised to a single
start; query route is refactored to use `SidecarPool` instead of per-request ephemeral sidecar.

**Independent Test**: Issue two consecutive `POST /kbs/{kb_id}/query` calls to the same KB.
The second call must return a valid answer in under 2 seconds. Verifiable without any other
user story being in place.

### Tests for User Story 1

- [X] T011 [P] [US1] Write failing unit test for `SidecarPool.get_or_start()` warm-cache path in `tests/unit/generator_api/test_pool.py`: mock a healthy `_SidecarEntry` in `_registry`; assert `_start_entry` is NOT called and the existing `SidecarProcess` is returned directly
- [X] T012 [P] [US1] Write failing unit test for `SidecarPool.get_or_start()` cold-start path in `tests/unit/generator_api/test_pool.py`: empty registry; assert `_start_entry` IS called, entry added to `_registry`, returned process matches newly created entry
- [X] T013 [P] [US1] Write failing unit test for `SidecarPool.get_or_start()` concurrent-same-KB serialisation in `tests/unit/generator_api/test_pool.py`: launch two concurrent `get_or_start()` coroutines for the same `kb_id`; assert `_start_entry` is called exactly once (second waiter reuses the entry created by the first)

### Implementation for User Story 1

- [X] T014 [US1] Implement `SidecarPool._start_entry(kb_id, kb_slug, container) -> _SidecarEntry` in `generator_api/pool.py`: compute `scratch_dir = settings.scratch_dir_root / kb_id`, create with `mkdir(parents=True, exist_ok=True)`, call `await asyncio.wait_for(asyncio.to_thread(sync_wiki_tree, ...), timeout=settings.sidecar_startup_timeout)`, call `await asyncio.to_thread(sidecar.start, ...)` and `await asyncio.to_thread(sidecar.init, kb_slug)`, log INFO at start and ready, return new `_SidecarEntry(process=sidecar, lock=asyncio.Lock())`
- [X] T015 [US1] Implement `SidecarPool._stop_entry(kb_id, entry, reason: str)` in `generator_api/pool.py`: call `entry.process.teardown()` (wrapped in `asyncio.to_thread`), then `shutil.rmtree(scratch_dir, ignore_errors=True)`, log INFO `f"Sidecar for kb_id={kb_id} stopped (reason: {reason})"`
- [X] T016 [US1] Implement `SidecarPool.get_or_start(kb_id, kb_slug, container) -> SidecarProcess` in `generator_api/pool.py`: (1) acquire `_registry_lock` briefly to get-or-create entry — if new entry, insert placeholder and release; (2) acquire `entry.lock`; (3) if `not entry.process.is_healthy()` or `entry.stale`, call `_stop_entry`, remove from registry, create fresh entry; (4) if cold start needed, call `_start_entry`; (5) release `entry.lock`; (6) return `entry.process` — follow two-lock ordering from data-model.md (registry lock NEVER held while entry lock is acquired)
- [X] T017 [US1] Add `SidecarPool.update_last_used(kb_id: str)` method to `generator_api/pool.py`: acquire `_registry_lock`, update `entry.last_used_at = time.monotonic()` if entry exists, release lock immediately
- [X] T018 [P] [US1] Refactor `POST /kbs/{kb_id}/query` route in `generator_api/router.py`: remove ephemeral `SidecarProcess` instantiation, `try/finally` teardown block, and `shutil.rmtree` calls; inject pool via `pool: SidecarPool = request.app.state.pool`; call `sidecar = await pool.get_or_start(str(kb_id), kb_slug, container)`; wrap query call in `asyncio.wait_for(asyncio.to_thread(sidecar.query, kb_slug, body.question), timeout=settings.generator_request_timeout)`; call `pool.update_last_used(str(kb_id))` on success; map `asyncio.TimeoutError` → 504 `"Query timed out after {N}s"`
- [X] T019 [P] [US1] Add `@asynccontextmanager async def _lifespan(app: FastAPI)` to `generator_api/app.py`: create `pool = SidecarPool(settings)`, set `app.state.pool = pool`, `yield`, then `await pool.shutdown()` in `finally` block; pass `lifespan=_lifespan` to the `FastAPI(...)` constructor (replace any existing lifespan or startup/shutdown event handlers)
- [X] T020 [US1] Write failing integration test for US1 acceptance scenarios in `tests/integration/generator_api/test_query_e2e.py`: (a) second query to same KB routes to existing sidecar (no second `_start_entry` call); (b) two concurrent first-queries result in exactly one `_start_entry` call; use mocked `SidecarPool` attached via `app.state.pool`

**Checkpoint**: Warm queries served without blob sync or process spawn; concurrent starts serialised

---

## Phase 4: User Story 4 — Clean Startup/Shutdown (Priority: P2)

**Goal**: All sidecar processes terminated on `SIGTERM`; crashed sidecars detected and restarted
on next query; no orphaned `openkb serve` processes after container restart.

**Independent Test**: Start service, warm a sidecar, stop service with `docker compose stop generator-api`. Verify `ps aux | grep "openkb serve"` shows no output.

### Tests for User Story 4

- [X] T021 [P] [US4] Write failing unit test for `SidecarPool.stop_kb()` in `tests/unit/generator_api/test_pool.py`: assert entry removed from `_registry` and `_stop_entry` called with correct `reason`; assert calling `stop_kb()` for an unknown `kb_id` is a no-op (no exception)
- [X] T022 [P] [US4] Write failing unit test for `SidecarPool.shutdown()` in `tests/unit/generator_api/test_pool.py`: populate registry with two entries; assert `_stop_entry` called for each and `_registry` is empty after shutdown
- [X] T023 [P] [US4] Write failing unit test for crash-detection path in `tests/unit/generator_api/test_pool.py`: mock `entry.process.is_healthy()` returning `False`; assert `SidecarCrashedError` is logged at WARNING, old entry is torn down, and `_start_entry` is called to create a fresh entry

### Implementation for User Story 4

- [X] T024 [US4] Implement `SidecarPool.stop_kb(kb_id: str)` in `generator_api/pool.py`: acquire `_registry_lock`, pop entry (no-op if absent), release lock, acquire `entry.lock`, call `_stop_entry(kb_id, entry, reason="stop_kb")`, release `entry.lock`
- [X] T025 [US4] Implement `SidecarPool.shutdown()` in `generator_api/pool.py`: acquire `_registry_lock`, snapshot all `(kb_id, entry)` pairs, clear `_registry`, release lock, then call `_stop_entry` sequentially for each entry with `reason="shutdown"`, log INFO `f"SidecarPool shut down ({n} sidecars stopped)"`
- [X] T026 [US4] Add crash-detection to `SidecarPool.get_or_start()` in `generator_api/pool.py`: after acquiring `entry.lock`, if entry exists and `not entry.process.is_healthy()`, log WARNING `SidecarCrashedError(kb_id)`, set `entry.stale = True` — the existing stale-restart path then drives teardown + fresh start (no duplicate code path needed)
- [X] T027 [US4] Update `generator_api/app.py` lifespan `finally` block: call `await pool.shutdown()` (already added in T019); add log INFO `"Generator API shutting down — terminating all sidecars"` before the shutdown call to confirm clean teardown is visible in container logs

**Checkpoint**: Service restarts leave zero orphaned `openkb serve` processes

---

## Phase 5: User Story 2 — Automatic Cache Invalidation (Priority: P2)

**Goal**: `compiler_worker` notifies `generator_api` after each document completes;
the next query to that KB gets a freshly restarted sidecar with the latest compiled content.

**Independent Test**: Compile a document, POST to `/kbs/{kb_id}/invalidate`, query the KB.
Verify fresh content is served. Testable independently of idle eviction.

### Tests for User Story 2

- [X] T028 [P] [US2] Write failing unit tests for `SidecarPool.invalidate()` in `tests/unit/generator_api/test_pool.py`: (a) existing entry gets `stale=True` and INFO is logged; (b) absent KB is a no-op (no error, DEBUG log); (c) stale flag is checked by `get_or_start()` on next call (can reuse T011-T013 test fixtures)
- [X] T029 [P] [US2] Write unit tests for `POST /kbs/{kb_id}/invalidate` route in `tests/unit/generator_api/test_router_invalidate.py`: (a) known KB with running sidecar → 204, `pool.invalidate()` called; (b) KB exists in DB but no sidecar → 204, `pool.invalidate()` called (no-op in pool); (c) unknown `kb_id` (not in DB) → 404; (d) malformed UUID → 422; verify `InvalidateRequest` body is optional
- [X] T030 [P] [US2] Write unit tests for `compiler_worker` invalidation call in `tests/unit/compiler_worker/test_job.py`: mock `httpx.AsyncClient.post`; assert POST is sent to `{config.generator_api_url}/kbs/{kb_id}/invalidate` after document reaches `complete`; assert job still completes successfully when httpx raises `httpx.ConnectError`; assert WARNING is logged on any exception

### Implementation for User Story 2

- [X] T031 [US2] Implement `SidecarPool.invalidate(kb_id: str)` in `generator_api/pool.py`: acquire `_registry_lock`, check if entry exists, release lock; if exists, set `entry.stale = True`, log INFO `f"KB {kb_id} marked stale"`; if absent, log DEBUG `f"invalidate called for KB {kb_id} with no active sidecar — no-op"` (no lock held longer than the registry lookup)
- [X] T032 [US2] Add `POST /kbs/{kb_id}/invalidate` route to `generator_api/router.py`: path param `kb_id: uuid.UUID` (FastAPI validates format → 422), async DB existence check (SELECT from `knowledge_bases` → 404 if missing), call `await request.app.state.pool.invalidate(str(kb_id))`, return `Response(status_code=204)`
- [X] T033 [US2] Update `compiler_worker/job.py`: immediately after the `logger.info("Job %s completed ...", ...)` log line, add `async with httpx.AsyncClient(timeout=5.0) as client: try: await client.post(f"{config.generator_api_url}/kbs/{kb_id}/invalidate", json={"document_id": str(document_id)}) except Exception: logger.warning("Failed to notify generator_api of invalidation for kb_id=%s", kb_id)` — import `httpx` at top of file
- [X] T034 [US2] Write failing integration test for full invalidation cycle in `tests/integration/generator_api/test_query_e2e.py`: (a) query warm KB, (b) POST `/kbs/{kb_id}/invalidate` → 204, (c) assert pool entry is now stale, (d) next query triggers `_start_entry` (verified via mock call count); use mocked pool; confirm contract: stale sidecar NOT immediately killed by `invalidate()`, only replaced on next `get_or_start()`

**Checkpoint**: Invalidation marks sidecar stale; next query transparently restarts with fresh content

---

## Phase 6: User Story 3 — Idle Sidecar Eviction (Priority: P3)

**Goal**: Sidecars idle longer than `GENERATOR_SIDECAR_IDLE_TTL_SECONDS` (default 1800 s)
are automatically evicted by a background asyncio task. Resources are freed without manual action.

**Independent Test**: Configure `GENERATOR_SIDECAR_IDLE_TTL_SECONDS=5` in tests, wait for eviction check, assert sidecar is stopped. A subsequent query restarts it. Does not depend on invalidation.

### Tests for User Story 3

- [X] T035 [P] [US3] Write failing unit tests for `SidecarPool._evict_idle()` in `tests/unit/generator_api/test_pool.py`: (a) entry with `last_used_at` older than `idle_ttl_seconds` is stopped and removed from `_registry`; (b) entry recently used is NOT evicted; (c) stale entry is evicted even if recently used (`stale=True` should also trigger eviction)
- [X] T036 [P] [US3] Write failing unit tests for `SidecarPool.evict_idle_loop()` in `tests/unit/generator_api/test_pool.py`: use `asyncio.CancelledError` injection to verify loop exits cleanly; assert `_evict_idle()` is called at least once per loop iteration; mock `asyncio.sleep` to avoid real waits in tests

### Implementation for User Story 3

- [X] T037 [US3] Implement `SidecarPool._evict_idle()` in `generator_api/pool.py`: acquire `_registry_lock`, snapshot entries where `(time.monotonic() - entry.last_used_at) > self._settings.sidecar_idle_ttl_seconds`, release lock; for each idle entry: acquire `entry.lock`, call `_stop_entry(kb_id, entry, reason="idle_eviction")`, acquire `_registry_lock`, remove from `_registry`, release both locks; log INFO `f"Evicting idle sidecar for kb_id={kb_id} (idle={elapsed:.0f}s > ttl={ttl}s)"`
- [X] T038 [US3] Implement `SidecarPool.evict_idle_loop()` in `generator_api/pool.py`: `while True: try: await asyncio.sleep(60); await self._evict_idle() except asyncio.CancelledError: logger.info("evict_idle_loop cancelled"); break` — the `CancelledError` must be re-raised (or `break`) to allow clean task cancellation from lifespan
- [X] T039 [US3] Update `generator_api/app.py` lifespan: after creating `pool` and before `yield`, add `eviction_task = asyncio.create_task(pool.evict_idle_loop())`; in `finally` block, call `eviction_task.cancel()` before `await pool.shutdown()` so the eviction loop stops cleanly before shutdown tears down sidecars
- [X] - [X] T040 [US3] Add optional pre-warm logic to `generator_api/app.py` lifespan: after `yield` (i.e., in the running phase, not blocking startup), if `settings.prewarm_on_startup`, query DB for KBs with at least one compiled document, schedule `asyncio.gather(*[pool.get_or_start(...) for kb in ready_kbs], return_exceptions=True)` as a background task; log WARNING for any individual KB that fails pre-warm; service startup is NOT blocked

**Checkpoint**: Idle sidecars evicted automatically; pool memory footprint bounded over long deployments

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Remove ephemeral sidecar patterns leftover from before the pool, write query-route
unit tests, update Docker Compose env, and run all quality gates.

- [X] - [X] T041 Remove all ephemeral `SidecarProcess` lifecycle code from `generator_api/router.py`: delete per-request `SidecarProcess()` instantiation, `try/finally sidecar.teardown()` block, `shutil.rmtree(scratch_dir)` call, and any `sync_wiki_tree` / `sidecar.init` calls — these now live exclusively in `SidecarPool._start_entry()`; confirm router only calls `pool.get_or_start()` and `pool.update_last_used()`
- [X] - [X] T042 [P] Write `tests/unit/generator_api/test_router_query.py`: unit tests for the refactored query route using mocked pool; assert (a) `pool.get_or_start()` is called with correct `kb_id`, `kb_slug`, `container`; (b) `pool.update_last_used()` is called after success; (c) 404 returned for unknown KB; (d) 409 returned for KB with no compiled docs; (e) 502 returned when `SidecarStartError` raised; (f) 504 returned on `asyncio.TimeoutError`; (g) response shape matches `QueryResponse` (answer, citations, tokens_used)
- [X] - [X] T043 [P] Add environment variable entries to `docker-compose.yml` for the `generator-api` service: `GENERATOR_SIDECAR_IDLE_TTL_SECONDS`, `GENERATOR_SIDECAR_STARTUP_TIMEOUT`, `GENERATOR_REQUEST_TIMEOUT`, `GENERATOR_PREWARM_ON_STARTUP`; add `GENERATOR_API_URL` to the `compiler-worker` service environment; include inline comments with default values
- [X] - [X] T044 Run `uv run ruff check .` and fix any lint errors in `generator_api/pool.py`, `generator_api/sidecar.py`, `generator_api/router.py`, `generator_api/app.py`, `generator_api/config.py`, `generator_api/exceptions.py`, `generator_api/models.py`, `compiler_worker/job.py`, `compiler_worker/config.py`
- [X] - [X] T045 Run `uv run ruff format --check .` and apply `uv run ruff format .` if any files fail the format check; commit formatting fixes separately
- [X] - [X] T046 Run `uv run bandit -r generator_api/ compiler_worker/` — verify zero new high/medium severity findings; expected safe: `subprocess.Popen` (existing, pre-approved), UUID path param validation (FastAPI type system), `httpx` usage (no shell invocation); annotate any `# nosec` suppressions with rationale if needed
- [X] - [X] T047 Run `uv run pytest tests/unit/generator_api/ tests/unit/compiler_worker/ -v` — confirm all unit tests pass including the new `test_sidecar.py`, `test_pool.py`, `test_router_query.py`, `test_router_invalidate.py`, and `test_job.py`; zero regression failures in existing `tests/unit/` suites
- [X] T048 Run `uv run pytest tests/integration/generator_api/ tests/integration/compiler_worker/ -v` — confirm integration tests pass; verify `tests/integration/compiler_worker/test_job_lifecycle.py` still passes unmodified (SC-006: no existing test breakage)

---

## Dependencies

### User Story Completion Order

```
Phase 1 (Setup)
    └── Phase 2 (Foundational)
            ├── Phase 3: US1 (P1) — MVP — Fast Repeated KB Queries
            │       └── Phase 4: US4 (P2) — Clean Startup/Shutdown  ← extends app.py lifespan from US1
            ├── Phase 5: US2 (P2) — Cache Invalidation              ← independent of US4
            └── Phase 6: US3 (P3) — Idle Eviction                   ← extends evict_idle_loop in pool.py
```

- **US1** (P1): Requires Phase 1 + 2 complete. No other story dependencies. ← Start here.
- **US4** (P2): Requires US1 (app.py lifespan wiring from T019). Extends `finally` block.
- **US2** (P2): Requires Phase 1 + 2 complete. Independent of US4 — can be worked in parallel by a second developer once US1 pool scaffold (T009) exists.
- **US3** (P3): Requires pool.py scaffold (T009). Adds `evict_idle_loop` — independent of US2 and US4.

### Within Each Phase

- Tests are written before or alongside implementation (TDD): write the failing test, then implement
- `_start_entry` (T014) → `get_or_start` (T016); `_stop_entry` (T015) → `stop_kb`/`shutdown`
- `pool.py` scaffold (T009) → all pool method implementations (T014–T017, T024–T026, T031, T037–T038)
- app.py lifespan init (T019) → lifespan shutdown (T027) → lifespan eviction wiring (T039)

---

## Parallel Opportunities

### Phase 1: All four setup tasks [P] together
```
T001 generator_api/config.py
T002 generator_api/exceptions.py
T003 generator_api/models.py
T004 compiler_worker/config.py
```

### Phase 2: After T005, T007 and T008 are parallel
```
T006 test_sidecar.py            (tests for T005)
T007 __init__.py files          (independent scaffolding)
T008 integration conftest.py    (independent scaffolding)
```

### Phase 3 (US1): Tests can be written in parallel, then implementations sequentially
```
T011, T012, T013 — parallel (all write to test_pool.py but non-overlapping test functions)
T014, T015       — parallel (different pool.py methods with no inter-dependency)
T018, T019       — parallel (different files: router.py + app.py)
```

### Phase 5 (US2): All three test tasks are parallel
```
T028 test_pool.py invalidate tests
T029 test_router_invalidate.py
T030 test_job.py compiler_worker tests
```

### Phase 6 (US3): Both test tasks are parallel
```
T035 _evict_idle tests
T036 evict_idle_loop tests
```

### Phase 7 (Polish): T042 + T043 are parallel; T044–T048 are sequential gates
```
T042 test_router_query.py
T043 docker-compose.yml
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004) — ~30 min
2. Complete Phase 2: Foundational (T005–T010) — ~1 hour
3. Complete Phase 3: US1 (T011–T020) — ~3–4 hours
4. **STOP and VALIDATE**: `uv run pytest tests/unit/generator_api/ -v` — confirm green
5. Run `docker compose up --build`, warm a sidecar, verify warm query < 2 s (quickstart §4–5)
6. Deploy/demo — this is the highest-value increment

### Incremental Delivery

1. **Foundation** (Phase 1+2) → pool scaffolded, SidecarProcess extended
2. **US1** (Phase 3) → warm queries, cold starts, concurrent dedup → **MVP**
3. **US4** (Phase 4) → clean shutdown, crash detection → **operationally correct**
4. **US2** (Phase 5) → cache invalidation, compiler_worker notification → **content freshness**
5. **US3** (Phase 6) → idle eviction → **resource bounded**
6. **Polish** (Phase 7) → code clean, tests green, Docker Compose updated → **PR ready**

### Parallel Team Strategy

With two developers after Phase 2 completes:
- **Developer A**: US1 (Phase 3) → US4 (Phase 4) → Polish (T041, T044–T048)
- **Developer B**: US2 (Phase 5) → US3 (Phase 6) → Polish (T042, T043)

---

## Notes

- **`rebuild_index_md()` does NOT exist** (research.md R-001): the spec assumption is inaccurate. The startup sequence is `sync_wiki_tree` → `sidecar.start` → `sidecar.init(kb_slug)`. Do not add a `rebuild_index_md` stub.
- **Two-lock ordering** (data-model.md §Concurrency contract): `_registry_lock` MUST be released before acquiring `entry.lock`. Never hold both simultaneously.
- **`asyncio.to_thread` for all blocking sidecar ops** (research.md R-003): `start()`, `init()`, `teardown()`, and `query()` are synchronous — always wrap in `asyncio.to_thread()`.
- **Startup timeout** applies to the entire `_start_entry` operation (blob sync + process start + init); **query timeout** (`generator_request_timeout`) applies only to the query call in the route handler.
- **`POST /kbs/{kb_id}/invalidate` has no auth** — explicitly out-of-scope per spec §Assumptions. Document this in the route handler docstring and in the PR description. MUST be secured before external/cloud deployment.
- **All new modules** must include `from __future__ import annotations` and `logger = logging.getLogger(__name__)` per project conventions (plan.md §Technical Context, constitution Principle III).

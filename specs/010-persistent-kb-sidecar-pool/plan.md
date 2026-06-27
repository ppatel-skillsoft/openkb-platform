# Implementation Plan: Persistent KB Sidecar Pool

**Branch**: `010-persistent-kb-sidecar-pool` | **Date**: 2026-06-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/010-persistent-kb-sidecar-pool/spec.md`

## Summary

Replace the current per-request ephemeral `SidecarProcess` lifecycle in `generator_api` with a
persistent `SidecarPool` that maintains at most one long-lived `openkb serve` subprocess per KB.
Repeat queries are served directly by the warm sidecar (target p99 < 2 s, vs. the current 5–15 s
cold start). Stale sidecars are invalidated by `compiler_worker` via a new
`POST /kbs/{kb_id}/invalidate` endpoint after each successful document compilation. Idle sidecars
are evicted by a background asyncio task. All sidecar processes are terminated cleanly on service
shutdown; no orphaned `openkb serve` processes may remain.

The design adds one new file (`generator_api/pool.py`), modifies five existing files in
`generator_api/`, adds one fire-and-forget HTTP call in `compiler_worker/job.py`, and introduces
two new test directories (`tests/unit/generator_api/` and `tests/integration/generator_api/`).
No new services are required; the Docker Compose stack is unchanged.

## Technical Context

**Language/Version**: Python 3.12 (`from __future__ import annotations` in every module)
**Primary Dependencies**: FastAPI 0.137.2, pydantic-settings, SQLAlchemy async 2.x, asyncio
(stdlib), httpx 0.27+ (compiler_worker fire-and-forget call), pytest + pytest-asyncio
**Storage**: PostgreSQL (document/KB state lookup); Azure Blob / Azurite (wiki blob tree sync)
**Testing**: pytest + pytest-asyncio; `ruff check`, `ruff format --check`, `bandit -r .` gates
MUST pass before PR creation
**Target Platform**: Docker Compose (local); AKS or Azure Container Apps (cloud)
**Project Type**: Internal service enhancement — `generator_api` module (pool lifecycle) +
`compiler_worker` (invalidation notification)
**Performance Goals**: Warm-query p99 latency < 2 s end-to-end within the service; cold-start
latency (first request or post-invalidation) unchanged at 5–15 s
**Constraints**: Per-KB process isolation MUST be maintained; at most one `openkb serve` process
per KB at any time; no shared in-memory state across KB sidecars; in-process asyncio pool only
(no Redis/distributed state); single-instance deployment (no horizontal scaling for this feature)
**Scale/Scope**: < 20 concurrently warm KBs in typical deployment; idle TTL default 1800 s;
startup timeout default 30 s; query timeout default 120 s (overrides existing 300 s — see
research.md)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Check | Principle | Status |
|-------|-----------|--------|
| Local Docker Compose stack runs end-to-end | I. Local-First | [x] No new services; existing stack unchanged |
| No secrets or API keys in source or config files | II. Security | [x] All secrets via env vars; `kb_id` UUID-validated before any FS ops |
| `bandit` passes with zero unresolved findings | II. Security / VIII. Test Discipline | [x] `subprocess.Popen` already present; no new shell-injection vectors; UUID input validated by FastAPI type system then checked |
| `ruff check` and `ruff format --check` pass | VIII. Test Discipline | [x] All new modules follow project conventions |
| All new modules have corresponding test files | VIII. Test Discipline | [x] `pool.py` → `tests/unit/generator_api/test_pool.py`; router changes covered by `test_router_query.py` + `test_router_invalidate.py`; `job.py` change → extended `test_job.py` |
| Per-KB data and process isolation is maintained | IV. Isolation | [x] Per-KB `asyncio.Lock`; per-KB scratch dir `{scratch_root}/{kb_id}/`; at most one process per KB; scratch cleaned on every stop |
| Storage backend uses abstract interface (not cloud-specific) | VI. Configurability | [x] `blob.py` unchanged; pool has no direct storage coupling |
| Logging uses `logging.getLogger(__name__)`, not `print` | III. Observability | [x] All new modules declare module-level loggers |
| `/health` and `/ready` endpoints present (if new service) | III. Observability | [x] No new service; existing `/health` in `app.py` unchanged |
| `openkb-core` dependency references a pinned git tag | II. Security | [x] No `openkb-core` changes in this feature |
| Feature branch targets `develop`, not `main` | Git Flow | [x] Branch `010-persistent-kb-sidecar-pool` off `develop` |
| All new behaviour covered by tests (unit + integration) | VIII. Test Discipline | [x] Unit tests for pool, router, invalidate; integration tests for end-to-end query cycle |

**Documented exception — invalidate endpoint authentication**: `POST /kbs/{kb_id}/invalidate`
carries no authentication token. This is explicitly out-of-scope per spec §Assumptions ("The
invalidate endpoint does not require authentication for this feature iteration; it is assumed to be
network-isolated within the Docker Compose stack"). This MUST be revisited before any external or
cloud deployment. Tracked in Complexity Tracking below.

## Project Structure

### Documentation (this feature)

```text
specs/010-persistent-kb-sidecar-pool/
├── plan.md                    # This file
├── research.md                # Phase 0 output
├── data-model.md              # Phase 1 output
├── quickstart.md              # Phase 1 output
├── contracts/
│   ├── invalidate-endpoint.md # POST /kbs/{kb_id}/invalidate contract
│   └── query-endpoint.md      # POST /kbs/{kb_id}/query (unchanged; documented for reference)
└── tasks.md                   # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (changes relative to current state)

```text
generator_api/
├── pool.py              # NEW — SidecarPool class + _SidecarEntry dataclass
├── sidecar.py           # MODIFIED — add last_used_at timestamp; add is_healthy() probe
├── router.py            # MODIFIED — query route uses pool.get_or_start(); add /invalidate route
├── app.py               # MODIFIED — pool init/teardown in lifespan; attach to app.state
├── config.py            # MODIFIED — add sidecar_idle_ttl_seconds (default 1800)
├── exceptions.py        # MODIFIED — add SidecarCrashedError
└── models.py            # MODIFIED — add InvalidateRequest Pydantic model

compiler_worker/
└── job.py               # MODIFIED — fire-and-forget invalidate call after document 'complete'

tests/
├── unit/
│   └── generator_api/           # NEW directory
│       ├── __init__.py
│       ├── test_pool.py         # SidecarPool unit tests (mocked SidecarProcess)
│       ├── test_router_query.py # Query route unit tests with mocked pool
│       └── test_router_invalidate.py  # Invalidate route unit tests
└── integration/
    └── generator_api/           # NEW directory
        ├── __init__.py
        ├── conftest.py          # TestClient + pool fixture
        └── test_query_e2e.py    # End-to-end query + invalidation cycle
```

**Structure Decision**: Single-project enhancement. No new top-level packages. Changes are
localised to `generator_api/` (pool + route + lifespan) and `compiler_worker/job.py` (one new
HTTP call). Tests mirror the source tree per constitution Principle VIII.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| `POST /kbs/{kb_id}/invalidate` has no auth | Spec explicitly out-of-scopes auth for this iteration; endpoint is internal Docker Compose network only | Adding auth would require a shared secret or token mechanism not yet designed for internal service-to-service calls; deferred to a dedicated security hardening feature |

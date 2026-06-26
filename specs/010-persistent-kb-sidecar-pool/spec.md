# Feature Specification: Persistent KB Sidecar Pool

**Feature Branch**: `010-persistent-kb-sidecar-pool`  
**Created**: 2026-06-26  
**Status**: Draft  
**Input**: User description: "Persistent KB Sidecar Pool — replace per-request ephemeral sidecar with a long-lived sidecar pool inside generator_api"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fast Repeated KB Queries (Priority: P1)

An end-user (or MCP client) queries a knowledge base that has already been initialised. Instead of waiting 5–15 seconds for a blob sync and process start, they receive an answer within 1–2 seconds because the sidecar is already running and warm.

**Why this priority**: This is the primary motivator for the feature. Eliminating cold-start latency on repeat queries is the most visible user-facing improvement and unblocks interactive MCP use.

**Independent Test**: Issue two consecutive `POST /kbs/{kb_id}/query` calls to the same KB. The second call must return a valid answer in under 2 seconds (excluding network). Verifiable without any other user story being in place.

**Acceptance Scenarios**:

1. **Given** a KB whose sidecar is already running, **When** a query is submitted, **Then** the response is returned without any blob download or process spawn occurring, and response time is under 2 seconds.
2. **Given** a sidecar that is currently starting up (first request), **When** a second concurrent query arrives for the same KB, **Then** the second query waits for the same sidecar to become ready and is served by it — no second sidecar is spawned.
3. **Given** a running sidecar, **When** the query is submitted and takes longer than the configured timeout (default 120 s), **Then** the system returns a meaningful timeout error to the caller without leaving a zombie process.

---

### User Story 2 — Automatic Cache Invalidation After Document Update (Priority: P2)

A content author publishes a new document. The compiler worker finishes compiling it. On the next query to that KB, the answer reflects the newly compiled content — the stale sidecar has been replaced transparently.

**Why this priority**: Without invalidation, the pool would serve outdated answers indefinitely. This story makes the pool correct, not just fast.

**Independent Test**: Compile a new document for a KB, trigger invalidation via `POST /kbs/{kb_id}/invalidate`, then query the KB. Verify the answer includes content from the new document. Testable independently of idle eviction or pool sizing.

**Acceptance Scenarios**:

1. **Given** a running sidecar for KB X, **When** `POST /kbs/{kb_id}/invalidate` is called, **Then** the sidecar is marked stale (not immediately killed) and the next query causes a fresh blob sync + sidecar restart before answering.
2. **Given** a stale sidecar is restarting while a query arrives, **When** the restart completes, **Then** the query is served by the new sidecar.
3. **Given** no sidecar is currently running for KB X, **When** `POST /kbs/{kb_id}/invalidate` is called, **Then** the call succeeds silently (no error) with no side effects.

---

### User Story 3 — Idle Sidecar Eviction Frees Resources (Priority: P3)

A KB that has not been queried for a configurable period (default 30 minutes) has its sidecar automatically stopped. When a query later arrives, the sidecar is restarted on demand.

**Why this priority**: Prevents memory and process accumulation in long-running deployments where many KBs exist but only a subset are actively used.

**Independent Test**: Configure a short idle TTL (e.g., 5 s in tests), wait for it to expire, then query the KB again. Verify the system correctly restarts the sidecar and answers the query. Does not depend on invalidation or pool sizing stories.

**Acceptance Scenarios**:

1. **Given** a sidecar that has been idle for longer than the configured TTL, **When** the eviction check runs, **Then** the sidecar is stopped and removed from the pool.
2. **Given** an evicted sidecar, **When** a new query arrives for that KB, **Then** a fresh sidecar is started and the query is answered correctly.
3. **Given** the idle TTL is set via the environment variable `GENERATOR_SIDECAR_IDLE_TTL_SECONDS`, **When** the service starts, **Then** the configured value is used rather than the default.

---

### User Story 4 — Service Starts and Shuts Down Cleanly (Priority: P2)

The `generator_api` service starts up without errors, accepts queries, and on graceful shutdown terminates all running sidecar processes cleanly — no orphaned `openkb serve` processes remain.

**Why this priority**: Operational correctness. Without clean shutdown, Docker Compose restarts and container orchestration leave orphaned processes consuming resources.

**Independent Test**: Start `generator_api` via Docker Compose, issue a query to warm a sidecar, then restart the service. Verify no `openkb serve` processes remain from the previous run.

**Acceptance Scenarios**:

1. **Given** the service starts, **When** the FastAPI lifespan begins, **Then** the `SidecarPool` is initialised and attached to `app.state`.
2. **Given** one or more sidecars are running, **When** the service receives a shutdown signal, **Then** all sidecar processes are terminated before the process exits.
3. **Given** a sidecar fails to start (e.g., blob sync error or `openkb serve` crashes), **When** a query is attempted, **Then** the query returns a meaningful error and the failed sidecar is not left in a broken state in the pool.

---

### Edge Cases

- What happens when two requests for the same KB arrive simultaneously and no sidecar exists yet? — Both must wait on the same per-KB lock; only one blob sync and one sidecar start occurs.
- What happens if `openkb serve` crashes unexpectedly mid-query? — The pool detects the dead process, removes it from the pool, and the caller receives an error. The next query triggers a fresh start.
- What happens if blob sync fails during sidecar startup? — The error is propagated to the caller; the KB is not left in a permanently broken state (retryable on next request).
- What happens if `POST /kbs/{kb_id}/invalidate` is called for a KB that does not exist in the system? — Returns a 404 or no-op 200 (acceptable either way); does not panic.
- What happens if the sidecar startup exceeds the configured `GENERATOR_SIDECAR_STARTUP_TIMEOUT`? — The startup is aborted, the process is killed, and a timeout error is returned to the query caller.
- How is per-KB data isolation preserved? — Each sidecar runs in its own scratch directory scoped to `kb_id`; no two KBs share a working directory.
- What happens to scratch directories when a sidecar is evicted or crashes? — Scratch directories are cleaned up when the sidecar stops (eviction, crash, or graceful shutdown).

---

## Security, Observability, and Isolation Notes *(mandatory)*

### Security Considerations

- **Authentication/authorisation**: The `POST /kbs/{kb_id}/invalidate` endpoint is internal — called by `compiler_worker` within the Docker Compose network. Authentication on this endpoint is explicitly out of scope for this feature (documented in constraints). No user-facing auth changes.
- **Input validation**: The `kb_id` path parameter must be validated as a well-formed UUID before any pool operations or filesystem operations. Malformed inputs must be rejected before any blob sync or process creation.
- **Secret handling**: No new secrets introduced. Azure Blob Storage credentials continue to be passed via existing environment variables. No credentials in logs or process arguments.
- **Process isolation**: Each sidecar process runs with the same OS user as `generator_api`; no privilege escalation. Scratch directories are isolated per KB UUID.

### Observability Considerations

- **Logging**: Key events to log at INFO level: sidecar start initiated, sidecar ready, sidecar stopped (reason: idle eviction / invalidation / shutdown / crash), query routed to existing sidecar. Log at WARNING when a sidecar crashes unexpectedly. Log at ERROR when startup fails.
- **Metrics**: No new Prometheus metrics in this feature (out of scope per constraints). Existing logging is sufficient for operational visibility.
- **Tracing**: No new trace spans required. Existing request-level tracing (if present) is unchanged.
- **Health/readiness impact**: The `/health` or `/ready` endpoint should not gate on sidecar readiness — the pool starts lazily. No changes to health check behaviour.

### Isolation Considerations

- **Per-KB data boundaries**: The pool is keyed by `kb_id` (UUID). Each sidecar operates on a scratch directory named after the KB UUID. Cross-KB data access is not possible through this mechanism.
- **Process isolation**: Each KB maps to at most one running `openkb serve` process at any time. The pool enforces this via per-KB asyncio locks.
- **Scratch/temp file cleanup**: Scratch directories (containing synced blobs and `index.md`) are created when a sidecar starts and deleted when it stops, regardless of stop reason (graceful, crash, eviction). No temp files persist between sidecar lifecycles.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST maintain at most one running `openkb serve` process per KB at any time.
- **FR-002**: On the first query for a KB (when no sidecar is running), the system MUST sync all wiki blobs from Azure Blob Storage, rebuild `index.md` using the existing `rebuild_index_md()` function, and start an `openkb serve` subprocess before answering the query.
- **FR-003**: Subsequent queries for a KB with a running sidecar MUST be routed directly to the existing process without any blob sync or process start.
- **FR-004**: The system MUST prevent concurrent sidecar starts for the same KB — multiple simultaneous queries must wait for a single startup to complete rather than each triggering their own.
- **FR-005**: The `POST /kbs/{kb_id}/query` route signature MUST remain unchanged (backward compatible with the existing MCP server interface).
- **FR-006**: A new `POST /kbs/{kb_id}/invalidate` endpoint MUST be provided. When called, it marks the KB's sidecar as stale so the next query triggers a fresh startup.
- **FR-007**: A sidecar that has not served any query for longer than `GENERATOR_SIDECAR_IDLE_TTL_SECONDS` (default 1800 seconds) MUST be automatically stopped and removed from the pool.
- **FR-008**: All sidecar processes MUST be terminated when `generator_api` shuts down (FastAPI lifespan teardown). No orphaned `openkb serve` processes may remain.
- **FR-009**: Query operations MUST time out after a configurable duration (default 120 seconds). Timed-out queries MUST return an error to the caller without leaving a zombie process.
- **FR-010**: Sidecar startup MUST time out after `GENERATOR_SIDECAR_STARTUP_TIMEOUT` seconds (default 30 seconds). A startup timeout MUST result in an error and a clean process kill.
- **FR-011**: If a running sidecar process crashes between queries, the pool MUST detect this on the next query attempt, clean up the dead process, and start a fresh one.
- **FR-012**: The `SidecarPool` MUST be created during FastAPI lifespan startup and stored on `app.state` so it is accessible across all request handlers.
- **FR-013**: The `GENERATOR_SIDECAR_IDLE_TTL_SECONDS` and `GENERATOR_SIDECAR_STARTUP_TIMEOUT` configuration values MUST be read from environment variables, with documented defaults applied when the variables are absent.
- **FR-014**: Scratch directories for each sidecar MUST be cleaned up when the sidecar stops, for any reason.

### Key Entities

- **SidecarProcess**: Represents a single long-lived `openkb serve` subprocess for one KB. Tracks process state (starting, ready, stale, stopped), last-query timestamp, and the scratch directory path.
- **SidecarPool**: Manages the collection of `SidecarProcess` instances keyed by KB UUID. Owns the per-KB asyncio locks, the idle eviction loop, and startup/teardown coordination.
- **KB UUID**: The stable identifier used as the pool key and as the scratch directory name. Ensures isolation between knowledge bases.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Repeat queries to a warm KB are answered in under 2 seconds (end-to-end within the service), compared to the current 5–15 seconds — a minimum 60% latency reduction on cached requests.
- **SC-002**: Two simultaneous first-queries for the same KB result in exactly one blob sync operation and one sidecar start — verified by log inspection or test assertion.
- **SC-003**: After a document is compiled and `invalidate` is called, the very next query to that KB returns content that includes the newly compiled document (freshness guarantee).
- **SC-004**: After `generator_api` is stopped, zero `openkb serve` processes remain running on the host — verified by process list inspection.
- **SC-005**: A sidecar idle for longer than the configured TTL is stopped within one eviction-check interval (TTL + check interval), and the KB returns to a startable state on the next query.
- **SC-006**: All existing unit and integration tests continue to pass without modification.
- **SC-007**: The Docker Compose stack (`docker-compose up`) starts and operates correctly without introducing new services.

---

## Assumptions

- The existing `generator_api/blob.py` `rebuild_index_md()` function is correct and reusable as-is; this feature does not need to modify it.
- The `openkb serve` subprocess interface (stdin/stdout protocol for init and query messages) is stable and will not change as part of this feature.
- The number of concurrently warm KBs in a typical deployment is small enough (< 20) that an in-process pool is sufficient; a distributed/Redis-backed pool is explicitly out of scope.
- The `compiler_worker` is responsible for calling `POST /kbs/{kb_id}/invalidate` after a document reaches `complete` status; this feature only needs to implement the endpoint, not the caller side.
- Azure Blob Storage credentials and connection configuration are already present in the environment; no new secret management is needed.
- The invalidate endpoint does not require authentication for this feature iteration; it is assumed to be network-isolated within the Docker Compose stack.
- Idle eviction uses a background asyncio task (periodic loop) rather than a per-sidecar timer; the eviction check interval is an implementation detail, not a configurable value for this feature.
- The feature targets single-instance deployment only; horizontal scaling with shared sidecar state is out of scope.

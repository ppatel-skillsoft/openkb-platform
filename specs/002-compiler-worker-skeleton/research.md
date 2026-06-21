# Research: Compiler Worker Skeleton (Phase 0)

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## R-001 — Redis Job Queue Strategy

**Question**: How should the worker consume jobs from Redis for local dev?
What message schema and error handling are needed?

**Decision**: Use `redis-py` (sync BRPOP with configurable timeout) on a
single Redis list key `compiler:jobs`. The worker blocks with a 5-second
timeout and loops, so Docker Compose teardown kills the process cleanly.

**Rationale**:
- `BRPOP` with a timeout is the simplest reliable queue pattern for a
  single-consumer, single-producer Phase 0 setup.
- `redis-py` is the standard Python Redis client; no extra abstraction
  library needed.
- A list-based queue requires zero Redis configuration (no Streams, no
  PubSub, no Lua scripts).
- The Azure Service Bus swap is a config-only change: implement a
  `QueueClient` protocol with a `RedisQueueClient` concrete class;
  `AzureServiceBusQueueClient` is wired in for production via env var
  `QUEUE_BACKEND=azservicebus` (out of scope for Phase 0).

**Alternatives considered**:
- *RQ (Redis Queue)*: Higher-level but adds a scheduler process and
  dashboard dependency not needed for Phase 0.
- *Celery*: Too heavy for a single-worker, single-task-type system.
- *Redis Streams*: Better at-least-once semantics but adds consumer-group
  management complexity not warranted for Phase 0.

**Message format**: JSON, base64-free. See
[contracts/job-queue-message.md](./contracts/job-queue-message.md).

---

## R-002 — Blob Storage Client (Azurite ↔ Azure)

**Question**: How should blob upload/download work locally (Azurite) and
transparently in production (Azure Blob Storage)?

**Decision**: Use `azure-storage-blob>=12.0.0` (`BlobServiceClient`) in both
environments. For local Azurite the client is constructed with the well-known
Azurite connection string or `AZURE_STORAGE_CONNECTION_STRING` env var. For
production, the same env var points at the real Azure endpoint (or a managed
identity credential is swapped in). No code changes are required between
environments.

**Rationale**:
- `azure-storage-blob` speaks the same REST wire protocol as Azurite and
  Azure Blob Storage; the client is environment-agnostic.
- Azurite ships with a fixed well-known connection string that is safe to
  hard-code as a default for Docker Compose (`UseDevelopmentStorage=true`
  maps to the Azurite default endpoint `http://127.0.0.1:10000/devstoreaccount1`).
- The container name for a KB follows the pattern `kb-{id}` (already
  established in spec 002 FR-008); no custom naming is needed.

**Alternatives considered**:
- *aiobotocore (S3 compatible)*: Azurite does not expose an S3-compatible
  endpoint by default; the Azure SDK is the canonical choice.
- *aiohttp raw HTTP*: Re-invents multipart upload, chunked transfer, and
  retry logic already handled by the SDK.

---

## R-003 — Sidecar Process Lifecycle and Port Allocation

**Question**: How does the worker spawn one sidecar per job, assign it an
isolated port, and guarantee teardown?

**Decision**: Port allocation via `socket.bind(('', 0))` + immediate release;
process launch via `subprocess.Popen` with the port passed as `--port`; a
`try / finally` block in `process_job()` calls `sidecar.teardown()` to
`SIGTERM` → `SIGKILL` (after 5 s grace) and `rmtree` the scratch dir.

**Rationale**:
- OS-assigned ports eliminate all port-collision races between sequential
  jobs and between the host and containerised worker.
- `subprocess.Popen` (sync) is used rather than `asyncio.create_subprocess_exec`
  because the overall worker loop is sync (Redis BRPOP is blocking); adding
  asyncio at the top level provides no benefit for Phase 0's sequential
  processing model.
- The `try / finally` teardown guarantee satisfies FR-012 and SC-006
  regardless of success, failure, or Python exception.
- The sidecar is started with the scratch directory as its CWD so that the
  OpenKB CLI's relative path assumptions (`./raw/`, `./wiki/`, `./.openkb/`)
  work without modification.

**Startup health check**: After `Popen`, poll `GET /health` (or any 200
response on `/`) with up to 30 retries × 0.5 s = 15 s max wait before
declaring the sidecar failed to start.

**Alternatives considered**:
- *Unix domain sockets*: Better security isolation, but the sidecar FastAPI
  app is assumed to use `--port`; UNIX socket support would require a sidecar-
  side change.
- *Pre-allocated port pool*: Fragile across restarts; OS assignment is
  simpler and more reliable.

---

## R-004 — Sidecar HTTP Contract (init / add / status)

**Question**: What request/response schemas do `/init`, `/add`, and `/status`
expose? (Branch `001-fastapi-http-api` is not yet merged, so this plan defines
the contract the worker will depend on.)

**Decision**: Three JSON endpoints on the FastAPI sidecar; the sidecar CWD is
the scratch directory so all paths are relative. See the full contract in
[contracts/sidecar-http-api.md](./contracts/sidecar-http-api.md).

**Rationale**:
- Thin HTTP wrappers around the existing `openkb init` and `openkb add` CLI
  code keep the sidecar minimal — it delegates to `compiler.compile_short_doc`
  / `compile_long_doc` exactly as the CLI does.
- A dedicated `GET /status` endpoint is needed because `add` triggers an async
  LLM compilation pipeline; the worker must poll rather than block on the HTTP
  response to allow future timeout enforcement.
- The status response includes the list of produced wiki pages so the worker
  can upload them to Blob Storage without walking the filesystem independently.

**Key contract points**:
- `POST /init` body: `{"model": "...", "language": "en"}` → initialises
  `.openkb/` in the sidecar's CWD.
- `POST /add` body: `{"filename": "source.md"}` (file already in CWD `raw/`)
  → starts async compilation; returns `{"job_id": "..."}`.
- `GET /status` → `{"status": "idle"|"compiling"|"complete"|"failed",
  "pages": [...], "token_cost": int|null, "pageindex_used": bool|null,
  "error": str|null}`.

---

## R-005 — Stale `compiling` Document Recovery on Startup

**Question**: When the worker restarts after a crash, some documents may be
stuck in `compiling` status indefinitely. How should these be resolved?

**Decision**: On worker startup (before entering the polling loop), query
`documents WHERE status = 'compiling'` (with a scoped `kb_id` filter).
For each row: set `status = 'failed'`, `failure_reason = 'Worker restarted
with job in progress — marked failed for safety'`, `updated_at = now()`.
Do not attempt to re-enqueue for Phase 0 (simpler; the operator can re-enqueue
manually via the seed/fixture tool).

**Rationale**:
- Marking stale jobs `failed` immediately satisfies FR-018 and SC-007 (queue
  does not stall).
- Re-enqueueing is risky without idempotency guarantees on the sidecar init
  step; deferred to Phase 1 when retry semantics are better understood.
- A single atomic SQL UPDATE is safe and auditable.

**Alternatives considered**:
- *Requeue automatically*: Can cause double-compilation if the previous run
  completed partially; safer as a Phase 1 enhancement.
- *Ignore stale jobs*: Violates FR-018 and SC-007.

---

## R-006 — Scratch Directory Isolation

**Question**: What ensures a scratch directory is unique per job and cleaned
up even on failure?

**Decision**: Create `tempfile.mkdtemp(prefix="openkb-job-")` at job start;
pass the path as the sidecar's CWD. Inside the scratch dir, create `raw/`
subdirectory and download the source document there. On teardown, call
`shutil.rmtree(scratch_dir, ignore_errors=True)`. If `rmtree` fails (e.g.
permission error), log a warning but do NOT block the next job — FR-013 and
the edge case "scratch cleanup fails" are both handled this way.

**Rationale**:
- `mkdtemp` guarantees uniqueness using the OS PRNG; no collision is possible
  between concurrent or sequential jobs.
- `ignore_errors=True` on cleanup ensures a single stuck file does not stall
  the worker.
- `raw/` sub-directory mirrors the OpenKB KB directory layout expected by
  the existing CLI and compiler code.

---

## R-007 — Missing Blob / Missing KB Row Edge Cases

**Question**: What should the worker do when the blob no longer exists in
Azurite, or when the `knowledge_bases` row is missing?

**Decision**:
- **Missing blob**: `BlobServiceClient.download_blob()` raises
  `ResourceNotFoundError`; catch it in `process_job()`, set document status
  to `failed` with `failure_reason = 'Source blob not found in storage'`,
  skip sidecar spawn entirely.
- **Missing KB row**: Query `knowledge_bases` for `kb_id` before starting the
  job; if `None`, set document status `failed` with
  `failure_reason = 'knowledge_bases row not found for kb_id: {id}'`.

Both cases satisfy the edge case enumerated in spec 002 and ensure clean
failure without sidecar spawn overhead.

---

## R-008 — Postgres Partial-Success (Wiki Pages Written, DB Update Fails)

**Question**: What happens if wiki pages are already written to Blob Storage
but the Postgres `wiki_pages` upsert fails?

**Decision**: Phase 0 does not implement two-phase commit or compensating
transactions. If the Postgres write fails after blob upload succeeds, the
document status remains `failed` (the exception propagates to the job error
handler). The blob pages are left in storage as orphans — they are named
deterministically (`kb-{id}/wiki/{slug}.md`) so a future retry can overwrite
them safely. This is explicitly documented as a known Phase 0 limitation.

**Rationale**: YAGNI. Adding saga / outbox patterns for Phase 0 single-worker
is premature. The deterministic blob path means orphaned pages are harmless
(idempotent overwrite on retry).

---

## R-009 — Worker Idle Behaviour (Empty Queue)

**Question**: Does the worker exit or idle when the queue is empty?

**Decision**: The worker idles indefinitely. `BRPOP` with a 5-second timeout
loops; on each empty poll cycle the worker logs a single DEBUG line and
continues. A `SIGTERM` or `SIGINT` handler sets a shutdown flag to exit the
loop cleanly.

**Rationale**: FR-001 implies a long-running service; an exit-on-empty
behaviour would require an external restart mechanism not present in Phase 0.

---

## R-010 — `pyproject.toml` Additions

The following packages must be added to `pyproject.toml` for this feature:

```toml
"redis>=5.0.0",
"azure-storage-blob>=12.0.0",
"httpx>=0.27.0",
"aiofiles>=23.0.0",
# Spec 001 additions (already established, listed for completeness):
"sqlalchemy[asyncio]>=2.0.0",
"asyncpg>=0.29.0",
"alembic>=1.13.0",
```

> **Note**: The existing `pyproject.toml` pins all dependencies exactly
> (supply-chain caution). During implementation, pin each new package to the
> latest verified release (e.g. `redis==5.0.4`).

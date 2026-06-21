# Feature Specification: Compiler Worker Skeleton (Phase 0)

**Feature Branch**: `003-compiler-worker-skeleton`  
**Created**: 2026-06-21  
**Status**: Draft  
**Input**: User description: "Build the Phase 0 compiler-worker skeleton for OpenKB Enterprise."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Document Compiles End-to-End (Priority: P1)

An operator places a document (e.g. a Markdown or text file) into Blob Storage and enqueues a compilation job. The compiler-worker picks up the job, downloads the document to a temporary scratch area, starts a dedicated sidecar process for that job, drives the sidecar through initialisation and document addition, waits for compilation to complete, uploads the resulting wiki markdown pages back to Blob Storage, records the outcome in Postgres, and tears down the sidecar.

**Why this priority**: This is the entire exit criterion for Phase 0. Every other story is in service of this one. The feature has no value until a document can be compiled end-to-end.

**Independent Test**: Can be fully tested by uploading a document to the local Azurite container, inserting a job onto the Redis queue, and observing that (a) wiki `.md` pages appear in Blob Storage under the expected path and (b) the `documents` row in Postgres moves to `complete` with non-null `token_cost` and `pageindex_used`. Delivers a working compilation pipeline.

**Acceptance Scenarios**:

1. **Given** a document blob exists in Azurite and a corresponding `documents` row is in Postgres with status `pending`, **When** a compilation job referencing that document is placed on the queue, **Then** the worker downloads the document, drives the sidecar through `init` and `add`, polls until compilation succeeds, uploads all produced wiki pages to Blob Storage, and sets the document status to `complete` in Postgres.
2. **Given** a successful compilation, **When** the sidecar returns a list of produced pages, **Then** a `wiki_pages` row is upserted in Postgres for every page, with correct `slug`, `blob_path`, `page_type`, `entity_type`, and `last_compiled_at`.
3. **Given** the worker completes a job, **When** the next job arrives, **Then** no scratch files, sidecar processes, or state from the previous job are present.

---

### User Story 2 - Failed Compilation Is Recorded Cleanly (Priority: P2)

When the sidecar fails to compile a document — because the sidecar process crashes, the sidecar returns an error response, or compilation times out — the worker records the failure in Postgres with a human-readable reason and releases the sidecar without crashing the worker itself. The worker then remains available to process the next job.

**Why this priority**: Without clean failure handling the worker becomes unreliable and stalls the queue, breaking the overall pipeline. It must degrade gracefully before the happy path is trusted.

**Independent Test**: Can be fully tested by enqueuing a job referencing a document that will cause the sidecar to return an error (e.g. a corrupt or empty file), then verifying that the `documents` row transitions to `failed` with a non-empty `failure_reason`, that no partial wiki pages are written, and that the worker continues to process a subsequent valid job.

**Acceptance Scenarios**:

1. **Given** a compilation job is picked up, **When** the sidecar returns an error on the `add` endpoint, **Then** the document status is set to `failed` with a failure reason captured from the sidecar response, and the sidecar process is torn down.
2. **Given** a compilation job is running, **When** the sidecar does not return a completed status within the configured timeout, **Then** the worker sets the document status to `failed` with a timeout reason, terminates the sidecar process, and cleans up the scratch directory.
3. **Given** a document is left in `compiling` state (e.g. from a previous worker crash), **When** the worker starts up, **Then** stale `compiling` documents are either requeued or marked `failed` so the queue does not stall permanently.

---

### User Story 3 - Local Dev Stack Runs via Docker Compose (Priority: P3)

A developer clones the repository, runs a single `docker compose up` command, and has a fully operational local environment: Postgres, Azurite, Redis, the OpenKB sidecar image, and the compiler-worker — all wired together and ready to accept jobs.

**Why this priority**: Local reproducibility is the primary development and testing contract for Phase 0. If the stack cannot be brought up reliably in one command, iterating on the worker is impractical.

**Independent Test**: Can be fully tested by running `docker compose up` from a clean checkout on a machine with Docker installed and verifying that all services reach a healthy state, that the worker log shows it is waiting for jobs, and that a manually enqueued job completes end-to-end (User Story 1) without any manual configuration.

**Acceptance Scenarios**:

1. **Given** a machine with Docker installed and the repository checked out, **When** `docker compose up` is executed, **Then** all five services (Postgres, Azurite, Redis, sidecar, compiler-worker) start and pass their health checks.
2. **Given** the local stack is running, **When** a test document is uploaded to Azurite and a job is placed on the queue, **Then** the end-to-end compilation completes successfully (matching User Story 1 acceptance criteria).
3. **Given** the local stack is running, **When** the compiler-worker process is started outside Docker (e.g. `python -m compiler_worker`) with environment variables pointing at the local services, **Then** it connects successfully and can process jobs identically to the containerised version.

---

### Edge Cases

- What happens when the sidecar process fails to start (port already in use, binary not found, or image not available)?
- How does the worker handle a document whose blob no longer exists in Azurite when the job is dequeued?
- What happens if a Postgres update fails after wiki pages have already been written to Blob Storage (partial success)?
- How does the worker behave when the queue is empty — does it idle or exit?
- What happens if scratch directory cleanup fails after a job — does it block the next job?
- How does the worker handle a `knowledge_bases` row that is missing for the KB referenced in the job?
- What happens if two sequential jobs are assigned the same dynamic port before the previous sidecar has fully released it?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The worker MUST consume compilation jobs from a queue, processing them sequentially (one at a time in Phase 0).
- **FR-002**: The worker MUST support Redis as the job queue for local development, with configuration that allows swapping to Azure Service Bus for production without code changes.
- **FR-003**: For each job, the worker MUST download the source document from Blob Storage into a unique, isolated temporary scratch directory.
- **FR-004**: The worker MUST start a dedicated sidecar process per job, bound to localhost only, using a dynamically assigned port or Unix socket to avoid port collisions.
- **FR-005**: The worker MUST call the sidecar's `init` endpoint to initialise the KB working tree in the scratch directory before the first document is added.
- **FR-006**: The worker MUST call the sidecar's `add` endpoint to submit the document for compilation.
- **FR-007**: The worker MUST poll the sidecar's `status` endpoint until compilation reports success or failure, or until a configurable timeout is reached.
- **FR-008**: On successful compilation, the worker MUST upload all produced wiki markdown pages to Blob Storage under the path `kb-{id}/wiki/`.
- **FR-009**: On successful compilation, the worker MUST upsert a `wiki_pages` row in Postgres for every page produced, recording `kb_id`, `page_type`, `slug`, `blob_path`, `entity_type`, and `last_compiled_at`.
- **FR-010**: The worker MUST update the `documents` row in Postgres to reflect the terminal outcome: status `complete` with `token_cost` and `pageindex_used` populated, or status `failed` with a `failure_reason`.
- **FR-011**: The worker MUST transition document status through the lifecycle: `pending` → `compiling` → `complete` or `failed`.
- **FR-012**: The worker MUST tear down the sidecar process and remove the scratch directory after every job, regardless of success or failure.
- **FR-013**: The worker MUST be stateless between jobs — no per-KB state, open handles, or scratch content may persist across job boundaries.
- **FR-014**: The worker MUST be runnable as a standalone Python process (e.g. `python -m compiler_worker`) using environment variables for all service connection details.
- **FR-015**: The local development environment MUST be fully orchestratable via a `docker-compose.yml` that includes Postgres, Azurite (Blob Storage emulator), Redis, the OpenKB sidecar, and the compiler-worker.
- **FR-016**: When compilation times out, the worker MUST record a timeout failure reason on the document and terminate the sidecar process cleanly.
- **FR-017**: When a sidecar error occurs, the worker MUST capture the error detail from the sidecar response and store it as the `failure_reason`.
- **FR-018**: The worker MUST handle stale `compiling` documents on startup (e.g. from a previous crash) by either requeuing them or marking them `failed`, so the queue does not stall.

### Key Entities

- **Compilation Job**: A queue message referencing a KB and a document to compile; consumed by the worker and processed to completion or failure.
- **Document**: A source file with a compilation lifecycle (pending → compiling → complete/failed); stores outcome metadata (`token_cost`, `pageindex_used`, `failure_reason`).
- **Wiki Page**: A compiled markdown output file; described by `slug`, `page_type`, `entity_type`, `blob_path`, and `last_compiled_at`; scoped to a KB.
- **Knowledge Base**: The organisational container for documents and wiki pages; provides `storage_container_path` and `compilation_config` read by the worker.
- **Sidecar Process**: A short-lived, per-job instance of the upstream OpenKB FastAPI application; isolated by localhost binding, unique scratch directory, and dynamic port; torn down after every job.
- **Scratch Directory**: A temporary working area created per job; holds the downloaded source document and the sidecar's working wiki tree; deleted after the job completes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A document uploaded to local Blob Storage results in its compiled wiki pages appearing in Blob Storage and all corresponding `wiki_pages` rows appearing in Postgres within a reasonable time (under 5 minutes for a typical document) after the job is enqueued.
- **SC-002**: Document status transitions are fully observable in Postgres — every job moves through `pending` → `compiling` → `complete` or `failed` with no documents stuck in `compiling` after the worker has finished processing.
- **SC-003**: The wiki pages produced by the worker are byte-for-byte identical to the pages produced by running the upstream OpenKB tool directly against the same input file.
- **SC-004**: The local Docker Compose stack starts to a healthy state and enables an end-to-end compilation test with no manual configuration steps beyond cloning the repository.
- **SC-005**: A failed compilation leaves the `documents` row in `failed` state with a non-empty, human-readable `failure_reason`, and the worker continues processing subsequent jobs without restarting.
- **SC-006**: No sidecar process, open port, scratch directory, or per-job state persists after a job completes — verified by inspecting the host after processing both a successful and a failed job.
- **SC-007**: On worker startup after a simulated crash, any documents left in `compiling` state are resolved (requeued or marked `failed`) so no job is permanently blocked.

## Assumptions

- The upstream OpenKB FastAPI sidecar (branch `001-fastapi-http-api`) exposes `/init`, `/add`, and `/status` endpoints and is available as a Docker image or buildable from source at development time.
- Phase 0 operates with a single KB; the worker reads the KB's configuration from Postgres and does not need to select or create KBs dynamically.
- No authentication or authorisation is required on any service in Phase 0 — all services communicate over a trusted local network (Docker Compose internal network or localhost).
- Redis is used as the job queue for local development; configuration for Azure Service Bus exists as an environment-variable swap but is not tested in Phase 0.
- Azurite is used as the Blob Storage emulator for local development; the same blob client code works against real Azure Blob Storage in production via environment-variable configuration.
- The Postgres schema (tables: `knowledge_bases`, `documents`, `wiki_pages`) is as defined in spec `001-phase0-postgres-schema`.
- The worker processes one job at a time in Phase 0; concurrent job processing and horizontal scaling are out of scope.
- The sidecar is started as a subprocess per job; it is not run as a long-lived shared service.
- Compilation timeout and polling interval use simple hardcoded or environment-configurable defaults; advanced retry policies, exponential backoff, and dead-letter queues are out of scope for Phase 0.
- Only `init`, `add`, and `status` sidecar operations are needed in Phase 0; `remove`, `recompile`, and `lint` are out of scope.
- The list of produced wiki pages and their metadata is obtained from the sidecar's `/status` response.
- Scratch directories are local to the worker's filesystem (or a named Docker volume); no distributed scratch storage is required.
- The worker logs to stdout; structured logging or centralised log aggregation is out of scope for Phase 0.

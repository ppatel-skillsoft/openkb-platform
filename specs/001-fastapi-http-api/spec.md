# Feature Specification: FastAPI HTTP API Layer

**Feature Branch**: `001-fastapi-http-api`
**Created**: 2026-06-19
**Status**: Draft
**Input**: User description: "Add a FastAPI-based HTTP API layer to OpenKB — an open-source CLI knowledge base tool (Python, Click) that compiles documents into a structured wiki using LLMs. The API should expose the core OpenKB operations (init, add document, query, list, status) as HTTP endpoints so that the knowledge base can be driven programmatically or integrated into other systems, without requiring the CLI."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Programmatic Integrator: Query a KB over HTTP (Priority: P1)

A developer has a running OpenKB knowledge base on a server and wants to query it from another
service (a Slack bot, a CI pipeline, a web dashboard) without shelling out to the CLI. They
send an HTTP request with their question and receive a structured JSON response containing the
answer, so they can parse and render it in their own UI.

**Why this priority**: Query is the primary read operation and the most common integration
target. Delivering it alone already yields a functional, end-to-end useful API.

**Independent Test**: Can be fully tested by `POST /kb/query` with a pre-populated KB directory
and verifying a structured JSON answer is returned — delivers immediate value without any other
endpoint.

**Acceptance Scenarios**:

1. **Given** a knowledge base at `kb_dir` that contains at least one compiled document,
   **When** a caller sends `POST /kb/query` with `{"question": "What is X?", "kb_dir": "<path>"}`,
   **Then** the server returns HTTP 200 with a JSON body containing at least `{"answer": "<text>"}`.

2. **Given** a valid KB with no documents compiled yet,
   **When** `POST /kb/query` is called,
   **Then** the server returns HTTP 200 with an answer that reflects the empty state (same
   behaviour as the CLI), not an error.

3. **Given** a request with a missing or blank `question` field,
   **When** `POST /kb/query` is called,
   **Then** the server returns HTTP 422 with a structured error body describing the validation
   failure.

4. **Given** a request pointing to a path that is not a valid KB directory,
   **When** `POST /kb/query` is called,
   **Then** the server returns HTTP 404 with a JSON body containing an actionable `detail`
   message.

---

### User Story 2 — System Integrator: Initialise a KB via HTTP (Priority: P2)

A DevOps engineer building an automated knowledge-base provisioning pipeline wants to initialise
a new KB on a remote server by calling an HTTP endpoint — no SSH or CLI access required.
They supply the target directory, model name, and language, and the server creates the KB
directory structure.

**Why this priority**: `init` is a prerequisite for all other operations on new deployments.
Automating it programmatically unblocks headless, server-side provisioning workflows.

**Independent Test**: Can be fully tested by `POST /kb/init` against an empty directory and
verifying `.openkb/config.yaml` exists with the expected values.

**Acceptance Scenarios**:

1. **Given** a directory that has no existing KB,
   **When** `POST /kb/init` is called with `{"kb_dir": "<path>", "model": "gpt-5.4-mini", "language": "en"}`,
   **Then** the server returns HTTP 200 and the directory contains `.openkb/config.yaml`,
   `.openkb/hashes.json`, `wiki/`, and `raw/`.

2. **Given** a directory that already contains a `.openkb/` folder,
   **When** `POST /kb/init` is called for that directory,
   **Then** the server returns HTTP 409 with a JSON body indicating the KB already exists —
   identical behaviour to the CLI message "Knowledge base already initialized."

3. **Given** a request with an invalid `model` value containing control characters,
   **When** `POST /kb/init` is called,
   **Then** the server returns HTTP 422 with a structured validation error.

---

### User Story 3 — Automation Pipeline: Add a Document via HTTP (Priority: P2)

A content pipeline (CI workflow, document-management system) needs to push newly-created
documents into an existing KB as soon as they are ready, without manual CLI intervention.
The caller supplies a file path accessible to the server and the KB directory; the server
converts, indexes, and compiles the document and reports success.

**Why this priority**: Adding documents is the primary write operation; it fills the KB with
content that makes query valuable. A pipeline that automates ingestion removes a major manual
step.

**Independent Test**: Can be fully tested by `POST /kb/add` with a known PDF/Markdown file path
and verifying the document appears in `POST /kb/list` afterwards.

**Acceptance Scenarios**:

1. **Given** a valid KB and a supported file at a path accessible to the server,
   **When** `POST /kb/add` is called with `{"kb_dir": "<path>", "source": "<file-path>"}`,
   **Then** the server returns HTTP 200 with `{"status": "added", "doc_name": "<slug>"}` once
   the document is fully compiled.

2. **Given** a file whose content is already in the KB (same hash),
   **When** `POST /kb/add` is called for that file again,
   **Then** the server returns HTTP 200 with `{"status": "skipped"}` — no duplicate work.

3. **Given** an unsupported file extension (e.g. `.zip`),
   **When** `POST /kb/add` is called,
   **Then** the server returns HTTP 422 with a JSON body listing the supported extensions.

4. **Given** a valid KB and a URL (`https://...`) as the `source` field,
   **When** `POST /kb/add` is called,
   **Then** the URL is fetched, saved to `raw/`, and processed identically to a local file —
   the response reflects the same `status` values as the file-based flow.

---

### User Story 4 — Monitoring Service: List and Status via HTTP (Priority: P3)

An operator monitoring multiple KB instances from a central dashboard polls the `list` and
`status` endpoints to display document counts, last-compile timestamps, and wiki health
metrics — without logging in to each server.

**Why this priority**: Read-only observability endpoints. Valuable for ops tooling but do not
block the core read/write workflow.

**Independent Test**: Can be fully tested independently by calling `GET /kb/status` and
`GET /kb/list` against a populated KB and verifying the returned JSON structure matches the
data visible via `openkb status` and `openkb list`.

**Acceptance Scenarios**:

1. **Given** a valid KB directory,
   **When** `GET /kb/status` is called with `?kb_dir=<path>`,
   **Then** the server returns HTTP 200 with a JSON object containing at minimum:
   `kb_dir`, `total_indexed` (int), `last_compile` (ISO-8601 timestamp or null),
   and per-subdirectory file counts.

2. **Given** a valid KB directory with indexed documents,
   **When** `GET /kb/list` is called with `?kb_dir=<path>`,
   **Then** the server returns HTTP 200 with a JSON object containing `documents`
   (array of objects with `name`, `doc_name`, `type`), `summaries`, `concepts`, and `entities`
   arrays.

3. **Given** a path that is not a valid KB,
   **When** `GET /kb/status` or `GET /kb/list` is called,
   **Then** the server returns HTTP 404 with an actionable `detail` message.

---

### Edge Cases

- What happens when `kb_name` refers to a KB that has never been initialised?
  → HTTP 404 with an actionable message ("KB 'x' not found; call POST /kb/init to create it").
- How does the system handle an `add` request for a URL that is unreachable?
  → HTTP 422 with a `detail` field describing the fetch failure.
- What happens when the LLM API key is missing or invalid during `add` or `query`?
  → HTTP 502 with a structured error body; the underlying LLM error message is included in `detail`.
- What happens when two concurrent `add` requests target the same KB from different API instances?
  → The Azure Blob lease serialises them; the second request waits, acquires the lease, and then
  succeeds (or reports its own status) — no data corruption.
- What happens when a `query` is sent to a KB that has no compiled content?
  → HTTP 200 with an answer that reflects the empty state (same as CLI behaviour) — not an error.
- What happens when the request body is well-formed JSON but violates semantic constraints (e.g. `model` contains a newline)?
  → HTTP 422 via Pydantic validation — same safeguards as `_coerce_model` / `_coerce_language` in the CLI.
- What happens if the Azure Blob lease cannot be acquired within a timeout?
  → HTTP 503 ("KB is busy; retry after a moment") — never silently corrupt shared state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose an `init` operation as `POST /kb/init` that creates a new
  knowledge base identified by a `kb_name` slug, accepting `kb_name`, `model`, and `language`
  as structured inputs and returning a structured JSON response.

- **FR-002**: The system MUST expose an `add` operation as `POST /kb/add` that ingests a document
  (URL or uploaded content) into an existing KB, returning a structured response with
  `status` (`added` | `skipped` | `failed`) and `doc_name`.

- **FR-003**: The system MUST expose a `query` operation as `POST /kb/query` that answers a natural
  language question against an existing KB and returns the answer as structured JSON.

- **FR-004**: The system MUST expose a `list` operation as `GET /kb/list` that returns the
  structured contents of a KB (documents, summaries, concepts, entities) as JSON.

- **FR-005**: The system MUST expose a `status` operation as `GET /kb/status` that returns
  structured KB health metrics (file counts per subdirectory, total indexed, last compile
  timestamp) as JSON.

- **FR-006**: All route handlers MUST use Pydantic models for request and response validation.
  No raw `dict` values may be returned from route handlers.

- **FR-007**: The API MUST enforce the same input validation rules as the CLI for `model`
  (≤ 100 characters, no control characters) and `language` (≤ 50 characters, no control
  characters).

- **FR-008**: Route handlers MUST contain no business logic; all KB operations MUST be
  implemented in shared service functions that are independently callable by the CLI.

- **FR-009**: All I/O-bound route handler operations (LLM calls, storage reads/writes) MUST be
  implemented as `async` functions.

- **FR-010**: The API MUST return consistent error shapes across all endpoints: a JSON object
  with at minimum a `detail` field containing a human-readable, actionable message.

- **FR-011**: The API server MUST be launchable via a CLI command (e.g. `openkb serve`) or
  directly via `uvicorn`, without requiring the core CLI for day-to-day operation.

- **FR-012**: The existing CLI commands (`openkb init`, `openkb add`, `openkb query`,
  `openkb list`, `openkb status`) MUST continue to function identically using the local
  filesystem storage backend — the API layer MUST NOT alter their behaviour.

- **FR-013**: All KB write operations through the API MUST be protected by distributed locking
  (Azure Blob lease on the KB's lock blob) to prevent data corruption under concurrent requests
  from multiple API instances.

- **FR-014**: The system MUST implement a `StorageBackend` abstraction with two concrete
  implementations: `LocalStorageBackend` (used by CLI and local dev) and
  `AzureBlobStorageBackend` (used by the cloud API). All KB operations MUST call only
  `StorageBackend` methods — no direct `pathlib.Path` or `os` filesystem calls in shared
  service code.

- **FR-015**: The active storage backend MUST be selected at startup via configuration
  (environment variable or config file) with no code changes required to switch between
  local and Azure Blob backends.

- **FR-016**: The Azure Blob backend MUST store each KB as a prefixed namespace within a
  single configured container (e.g. `<container>/<kb_name>/wiki/`, `<container>/<kb_name>/raw/`),
  with connection credentials supplied via environment variables and never hardcoded.

- **FR-017**: The project MUST include a `docker-compose.yml` that runs the API and an Azurite
  (Azure Blob Storage emulator) service together, so the full Azure Blob storage path is
  exercisable locally without any cloud account. Running `docker compose up` MUST be sufficient
  to start a fully functional local stack.

- **FR-018**: The project MUST include a `Dockerfile` for the API service. The image MUST
  install only the `[api]` extra and start the server via `openkb serve`.

- **FR-019**: The `AzureBlobStorageBackend` MUST work unchanged against both Azurite and
  real Azure Blob Storage — the only difference is the `AZURE_STORAGE_CONNECTION_STRING` value.
  No code path may special-case local vs. cloud.

### Key Entities

- **StorageBackend** *(abstraction)*: Interface implemented by both local and Azure Blob backends.
  Methods cover: read file, write file (atomic), delete file, list prefix, acquire lock,
  release lock. Async throughout.
- **LocalStorageBackend**: Implements `StorageBackend` over the local filesystem using
  `pathlib.Path`. Uses `portalocker` for locking. Used by CLI and local dev server.
- **AzureBlobStorageBackend**: Implements `StorageBackend` over Azure Blob Storage.
  Uses Blob lease API for distributed locking. Used by cloud API deployment.
- **KBInitRequest**: Input for initialising a KB — `kb_name` (slug, ≤ 64 chars, `[a-z0-9-_]`),
  `model` (optional), `language` (optional).
- **KBInitResponse**: Outcome of init — `kb_name`, `status` ("created" | "exists"),
  `message` (human-readable).
- **KBAddRequest**: Input for adding a document — `kb_name`, `source` (URL; file upload via
  multipart is a future enhancement).
- **KBAddResponse**: Outcome of add — `status` ("added" | "skipped" | "failed"), `doc_name`
  (optional), `message` (human-readable).
- **KBQueryRequest**: Input for querying — `kb_name`, `question` (non-blank string),
  `save` (bool, default false).
- **KBQueryResponse**: Query result — `answer` (string), `saved_to` (optional blob path if
  `save=true`).
- **KBListResponse**: KB contents — `documents` (array), `summaries` (array), `concepts`
  (array), `entities` (array), `reports` (array). Each item carries `name`, `doc_name`, `type`.
- **KBStatusResponse**: KB health snapshot — `kb_name`, `total_indexed` (int),
  `last_compile` (ISO-8601 or null), `last_lint` (ISO-8601 or null),
  `directory_counts` (mapping of subdir name → file count).
- **ErrorResponse**: Uniform error shape — `detail` (human-readable actionable message).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five core operations (init, add, query, list, status) are accessible via HTTP
  without invoking the CLI, verified by an automated test suite that exercises each endpoint
  end-to-end against both storage backends.

- **SC-002**: The API can be started and serve its first request within 5 seconds of the
  `openkb serve` command on a standard developer machine, with no manual configuration beyond
  what the CLI already requires.

- **SC-003**: Every endpoint returns a structured, machine-parseable JSON response body for both
  success and error cases — verified by contract tests that assert on response schema.

- **SC-004**: The existing CLI test suite passes without modification after the API and storage
  abstraction layers are introduced — zero regressions in CLI behaviour with the local backend.

- **SC-005**: Concurrent add requests to the same KB from multiple API instances do not produce
  corrupted or partial state, verified by a test that sends simultaneous `POST /kb/add` requests
  and asserts both resolve cleanly (one "added", one "skipped" or sequentially "added"), with the
  Azure Blob lease preventing a race condition.

- **SC-006**: All new code achieves test coverage equivalent to the existing codebase standard:
  unit tests for shared service functions and both storage backend implementations, integration
  tests for all route handlers, and at least one contract test per endpoint asserting on the
  documented response schema.

- **SC-007**: Switching from local to Azure Blob storage (and from Azurite to real Azure)
  requires only environment variable changes — no code changes — verified by running the same
  integration test suite against both backends.

- **SC-008**: `docker compose up` starts the full local stack (API + Azurite) and the API
  is reachable at `http://localhost:8000` within 10 seconds, verified by a `curl /kb/status`
  smoke test in the quickstart.

## Assumptions

- The API operates in a trusted internal environment; no authentication or authorisation layer
  is required for this initial version. Callers are assumed to be internal services or
  authorised operators.
- The `openkb serve` command will use `uvicorn` as the ASGI server. Host and port are
  configurable via CLI options (e.g. `--host`, `--port`) with sensible defaults.
- The API does not stream query responses; it always returns the complete answer in a single
  response. Streaming support is deferred to a future enhancement.
- `POST /kb/add` with a URL source downloads the content to a temporary buffer before uploading
  to Blob storage for processing — subject to the same network availability requirements as
  `openkb add <url>`.
- The `print_list` and `print_status` functions in `cli.py` will be refactored into shared
  service functions that return data structures rather than printing, enabling both the CLI
  and API to consume them.
- `fastapi`, `uvicorn`, and `azure-storage-blob` will be added as optional dependencies under
  an `[api]` extra in `pyproject.toml`, keeping the base CLI install lightweight.
- Each KB is identified by a `kb_name` slug stored as a prefix in a single Azure Blob container.
  The container name and Azure connection string are supplied via environment variables
  (`AZURE_STORAGE_CONNECTION_STRING`, `AZURE_KB_CONTAINER`).
- The CLI continues to use `LocalStorageBackend` backed by `pathlib.Path` and `portalocker`;
  no changes to the CLI's file-access patterns are required.
- **Local development uses Azurite** (Microsoft's Azure Blob Storage emulator) via Docker Compose.
  The `AzureBlobStorageBackend` connects to Azurite using its well-known connection string
  (`DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;...;BlobEndpoint=http://azurite:10000/devstoreaccount1`).
  Promoting to real Azure requires only replacing that connection string. No Azure account is
  needed for local development or CI.
- A `.env.docker` example file will document the Azurite connection string; a `.env.azure`
  example will document the production Azure connection string. Neither is committed with
  real credentials.

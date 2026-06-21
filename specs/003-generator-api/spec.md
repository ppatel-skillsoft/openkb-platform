# Feature Specification: Phase 0 Generator API Service

**Feature Branch**: `004-generator-api`
**Created**: 2026-06-21
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Developer Submits a Query and Gets a Grounded Answer with Citations (Priority: P1)

A developer (or an internal tool) sends a question to the generator-api service for a given knowledge base. The service locates the compiled wiki content for that KB, spins up the OpenKB sidecar against it, proxies the question to the sidecar's query endpoint, and returns a grounded answer with full citations back to the caller — all as a single HTTP request/response.

**Why this priority**: This is the only feature of Phase 0. Every other story depends on this core query flow working end-to-end. Without it, the service has no value.

**Independent Test**: Can be fully tested by sending `POST /kbs/{kb_id}/query` with a question to a running local stack (Docker Compose) and verifying the response contains a non-empty `answer` field and at least one entry in `citations` that references a source document in the compiled wiki.

**Acceptance Scenarios**:

1. **Given** the Docker Compose stack is running, a knowledge base record exists in the database, and the KB has at least one compiled document, **When** a caller sends `POST /kbs/{kb_id}/query` with a valid `question`, **Then** the service returns HTTP 200 with a JSON body containing `answer` (non-empty string), `citations` (array, may be empty for trivial questions but structure must be present), and `tokens_used` (integer).
2. **Given** the same query is sent twice to the same KB, **When** both responses are received, **Then** both responses contain semantically equivalent answers — the service is stateless and does not persist query state between calls.
3. **Given** a compiled wiki tree exists in Blob Storage (Azurite) for the KB, **When** the query request arrives, **Then** the service syncs the wiki content to a local scratch directory, passes it to the sidecar, and the sidecar produces an answer grounded in that content (not hallucinated).
4. **Given** the upstream sidecar returns citations referencing source document paths, **When** the generator-api returns its response, **Then** all citation objects from the sidecar response are preserved verbatim in the caller's response — no citation data is dropped or modified.

---

### User Story 2 — Service Rejects Query for a KB That Is Not Ready (Priority: P1)

A caller tries to query a KB that either does not exist in the database, or exists but has no compiled documents. The service detects this before spending any resources on sidecar spin-up and returns a clear, actionable error.

**Why this priority**: Failing fast before expensive operations (wiki sync, sidecar start) protects local resources and gives the caller an immediately useful error message. Required for reliable Phase 0 operation.

**Independent Test**: Can be tested independently by sending a query for a `kb_id` that has no compiled documents and verifying a 4xx error response with a descriptive message is returned.

**Acceptance Scenarios**:

1. **Given** a `kb_id` that does not exist in the `knowledge_bases` table, **When** a caller sends `POST /kbs/{kb_id}/query`, **Then** the service returns HTTP 404 with a JSON error body explaining the KB was not found.
2. **Given** a KB exists in the database but all its documents have a status other than `complete`, **When** a caller sends `POST /kbs/{kb_id}/query`, **Then** the service returns HTTP 409 (or HTTP 422) with a JSON error body indicating the KB has no compiled content available.
3. **Given** a valid `question` field is missing from the request body, **When** a caller sends `POST /kbs/{kb_id}/query`, **Then** the service returns HTTP 422 with a JSON error body identifying the missing field.

---

### User Story 3 — Service Starts and Is Reachable in Docker Compose Without External Dependencies (Priority: P1)

A developer clones the repository, runs the Docker Compose stack, and the generator-api service is healthy and reachable at its configured port — using only local containers (Azurite for Blob Storage, Postgres for metadata) with no Azure service dependencies.

**Why this priority**: Local-first is a hard architectural requirement. The service must be independently operable on a developer's laptop without Azure credentials or cloud connectivity.

**Independent Test**: Can be tested on a clean machine by running the compose command and sending `GET /health` (or equivalent) to the generator-api container, verifying it returns a 200 response indicating all required local dependencies (Postgres, Azurite) are reachable.

**Acceptance Scenarios**:

1. **Given** Docker is available and the repository is cloned, **When** the developer starts the Docker Compose stack, **Then** the generator-api container starts successfully, passes its health check, and is reachable on its configured port within a reasonable startup period.
2. **Given** the stack is running, **When** the developer inspects the service's environment configuration, **Then** all connection strings point to local Compose services (Azurite, Postgres) and no Azure subscription credentials are required.
3. **Given** the service is running, **When** a developer sends a request directly using `curl` or a similar tool from outside the Compose network, **Then** the service responds correctly — confirming it is independently accessible for debugging without a gateway in front of it.

---

### User Story 4 — Developer Can Run generator-api as a Standalone Python Process for Debugging (Priority: P2)

A developer can start the generator-api service directly as a Python process (outside Docker) for local debugging, without needing the full Compose stack — provided the required environment variables are set to point at locally accessible services.

**Why this priority**: Speeds up the inner development loop significantly. Developers should not need to rebuild containers to test a code change.

**Independent Test**: Can be tested by exporting the required environment variables and running the service entrypoint directly, then sending a health-check request and verifying a valid response.

**Acceptance Scenarios**:

1. **Given** the required environment variables are exported (database URL, blob endpoint, sidecar image reference), **When** the developer starts the service as a standalone Python process, **Then** the service starts without errors and responds to requests.
2. **Given** the service is running as a Python process, **When** a valid query request is sent, **Then** the service behaves identically to its containerised counterpart — the same code path is exercised.

---

### Edge Cases

- What happens when Azurite is unavailable at query time? The service must fail the request with a 503 and a descriptive message rather than silently returning a malformed answer.
- What happens when the sidecar process fails to start (e.g., image missing, port conflict)? The service must return a 502/503 error and clean up any partial sidecar state before responding.
- What happens when the sidecar starts but times out before returning a response? The service must enforce a request-scoped timeout and return a 504 to the caller.
- What happens when the wiki sync from Azurite partially fails (some files missing)? The service must fail the query rather than letting the sidecar run against an incomplete wiki tree.
- What happens when the `kb_id` in the URL path contains characters that could be interpreted as a path traversal (`../`, encoded slashes)? The service must validate and reject such inputs before using them in any file system or storage operation.
- What happens when the `save` parameter is included in the request body? It must be accepted and silently ignored — no error, no persistence.
- What happens when the sidecar returns an empty `citations` array for a legitimate question? This is valid; the service must pass it through rather than treating it as an error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service MUST expose `POST /kbs/{kb_id}/query` accepting a JSON body `{ "question": string, "save"?: boolean }` and returning `{ "answer": string, "citations": array, "tokens_used": integer }`.
- **FR-002**: The service MUST read `knowledge_bases` table to resolve the `storage_container_path` for the given `kb_id` before initiating any wiki sync or sidecar operation.
- **FR-003**: The service MUST read the `documents` table and verify at least one document for the given `kb_id` has `status = 'complete'` before accepting a query; if none exist, it MUST return a 4xx error.
- **FR-004**: The service MUST sync the compiled wiki tree from Blob Storage (Azurite in local dev) to a per-request scratch directory before invoking the sidecar.
- **FR-005**: The service MUST start a dedicated OpenKB FastAPI sidecar process pointing at the per-request wiki scratch directory and call the sidecar's `query` endpoint with the incoming question.
- **FR-006**: The sidecar process lifecycle MUST be scoped to the query request in Phase 0 — the sidecar is spun up for the request and torn down (or left to exit) after the response is received; sidecars MUST NOT be shared across concurrent requests or across knowledge bases.
- **FR-007**: The service MUST preserve and return all citation objects from the sidecar's response verbatim — no citations may be dropped, modified, or substituted.
- **FR-008**: The `save` request parameter MUST be accepted without error and MUST be treated as a no-op in Phase 0 (no session persistence).
- **FR-009**: The service MUST enforce a per-request timeout on the sidecar call; if the timeout is exceeded, the service MUST return HTTP 504 and clean up the sidecar process.
- **FR-010**: The service MUST return HTTP 404 when the `kb_id` does not exist in the database.
- **FR-011**: The service MUST expose a health-check endpoint that confirms reachability of Postgres and Azurite.
- **FR-012**: All configuration (database URL, blob storage endpoint and credentials, sidecar image/binary path, scratch directory root, request timeout) MUST be provided via environment variables with no hard-coded values.
- **FR-013**: The service MUST be runnable as a standalone Python process for local debugging, not only as a Docker container.
- **FR-014**: The service MUST be part of the shared Docker Compose stack, using the same Postgres and Azurite containers defined for other Phase 0 services — no new infrastructure containers are required.
- **FR-015**: The service MUST NOT require any authentication token or API key on incoming requests in Phase 0.

### Key Entities

- **KnowledgeBase**: Represents a compiled knowledge base. Key attributes consumed by this service: `id` (UUID), `storage_container_path` (path prefix in Blob Storage pointing to the compiled wiki tree), `status`. Read-only in Phase 0.
- **Document**: Represents a source document within a KB. Key attribute consumed: `kb_id` (foreign key), `status` (must be `complete` for the KB to be queryable). Read-only in Phase 0.
- **QueryRequest**: The inbound payload from the caller: `question` (string, required), `save` (boolean, optional, no-op in Phase 0).
- **QueryResponse**: The outbound payload returned to the caller: `answer` (string), `citations` (array of citation objects as returned by the sidecar), `tokens_used` (integer).
- **WikiScratchDirectory**: A per-request temporary directory on the local file system populated by syncing the KB's compiled wiki tree from Blob Storage. Used as the sidecar's data root. Cleaned up after the request completes.
- **OpenKBSidecar**: An instance of the OpenKB FastAPI application (`001-fastapi-http-api` branch), spawned per query request, bound to localhost, pointed at the WikiScratchDirectory. Torn down after the response is received.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer with a clean clone and Docker installed can bring up the full local stack and successfully receive a grounded answer with citations from a query request within 30 minutes — with no Azure credentials required.
- **SC-002**: The query response from generator-api for a given question is semantically equivalent to the response obtained by calling the OpenKB upstream `query` endpoint directly against the same compiled wiki — confirming the proxy adds no quality degradation (Phase 0 exit criterion).
- **SC-003**: 100% of citation objects returned by the upstream sidecar appear unchanged in the generator-api response for every query — the trust feature is never silently broken.
- **SC-004**: The service returns an actionable error response (4xx or 5xx with a JSON error body) for all defined failure modes (KB not found, no compiled documents, sidecar timeout, blob sync failure) — no silent failures or unhandled exceptions exposed to callers.
- **SC-005**: The service starts as a standalone Python process (no Docker) in under 10 seconds given correct environment variables, confirming it is independently debuggable.
- **SC-006**: End-to-end query latency (wall clock from HTTP request to response) is observable and logged per request, providing a baseline for future optimisation decisions.

## Assumptions

- The OpenKB FastAPI sidecar (`001-fastapi-http-api` branch) exposes a `POST /query` (or equivalent) endpoint that accepts a `question` and returns `{ answer, citations, tokens_used }`. The exact path will be confirmed against that branch.
- The compiled wiki tree written to Blob Storage by the compiler-worker is a directory tree that the sidecar can be pointed at via a configuration parameter or environment variable — the sidecar does not require a database connection.
- Azurite is already configured in the Docker Compose stack by the compiler-worker spec (spec `002`) and does not need to be re-provisioned here; generator-api shares the same Azurite container.
- Postgres is already running in the Compose stack (spec `001`); generator-api reads the `knowledge_bases` and `documents` tables using the same connection configuration as compiler-worker.
- The `storage_container_path` in the `knowledge_bases` table is sufficient to locate and download the full compiled wiki tree from Blob Storage.
- Phase 0 is single-KB: for initial testing there will be exactly one KB in the database; the service is nonetheless written to accept any valid `kb_id` to avoid hardcoding.
- Query volume in Phase 0 is low (internal developer use); spin-up-per-request sidecar lifecycle is acceptable even if it introduces several seconds of latency per query. Performance optimisation is deferred to a future phase.
- The sidecar binary or Docker image is available in the local environment (built or pulled before the stack starts); the generator-api service does not build or pull the sidecar image at runtime.
- No rate limiting, authentication, or authorisation is required in Phase 0; the service is internal-use only.
- Chat session persistence (`save = true` behaviour) is explicitly out of scope for this specification. The `save` parameter is accepted to maintain API compatibility with the full spec (`06-api-spec.md`) but is a no-op until Step 4.
- The `tokens_used` value is passed through from the sidecar response and is not computed or validated by generator-api itself.

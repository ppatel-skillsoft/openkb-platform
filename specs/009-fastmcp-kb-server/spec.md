# Feature Specification: FastMCP Knowledge Base Server

**Feature Branch**: `feature/009-fastmcp-kb-server`
**Created**: 2026-06-26
**Status**: Draft
**Input**: User description: "I would like to add mcp server using fastmcp that users would be able to plug into their agents or mcp hosts like Claude, Cursor, Github Copilot and leverage all the knowledge from the knowledge base. With this I am planning to move into more end users side of things - which is consumption of the knowledge built using compiler jobs. In order for this to be tested out successfully, we need real world domain specific documents, and I am going to start with Marketing. I will provide the documents which are not to be committed to git but are to be used to create a kb. You can locate the documents in marketing_kb dir at the root of the project. While ingesting the documents, we want to make sure we don't throttle OpenAI and fail due to 429 - Too Many Requests - make sure to employ an appropriate strategy for that. The FastMCP server must expose only the tools that makes sense and do not bloat the context. We can keep security and other things at bay for now - the aim is to get all this working locally through our docker compose stack while aligning with the product mindset - so make sure to make right architecture decisions."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Query Knowledge Base via MCP (Priority: P1)

A marketing professional or AI engineer has an MCP host (e.g. Claude Desktop, GitHub Copilot agent, Cursor) connected to the OpenKB MCP server. They ask a natural-language question — "What are our competitive differentiators against Cornerstone?" — and the MCP tool fetches a grounded, citation-backed answer from the compiled marketing knowledge base without the user ever leaving their agent environment.

**Why this priority**: This is the core value proposition of the feature — knowledge consumption through the AI tooling ecosystem. All other stories exist to enable this one.

**Independent Test**: Can be tested end-to-end by configuring an MCP host against the running `mcp-server` container, sending a question, and asserting that a non-empty, citation-bearing answer is returned within an acceptable timeout.

**Acceptance Scenarios**:

1. **Given** the MCP server is running and the `marketing` KB has compiled documents, **When** an MCP tool call `ask_kb` is made with question "What messaging do we use for AI readiness?", **Then** the MCP server returns an answer with at least one citation from the compiled wiki.
2. **Given** an MCP host sends an `ask_kb` call with an empty question, **When** the tool validates the input, **Then** the MCP server returns a structured error and does not forward the request downstream.
3. **Given** the downstream `generator-api` is temporarily unavailable, **When** an `ask_kb` call arrives, **Then** the MCP server returns a clear error message rather than hanging indefinitely.

---

### User Story 2 — Discover Available Knowledge Bases (Priority: P2)

An agent or developer wants to know which knowledge bases are available before querying, so they can address the right knowledge domain. The MCP tool `list_kbs` returns a compact list of available, ready-to-query knowledge bases.

**Why this priority**: Without discoverability, a user must hard-code KB identifiers. This tool enables dynamic, multi-KB agent workflows and better agent self-selection of the correct knowledge source.

**Independent Test**: Can be tested by calling `list_kbs` with no arguments against a stack with at least one compiled KB and asserting a non-empty list is returned, each entry containing at minimum a name/identifier and description.

**Acceptance Scenarios**:

1. **Given** the `marketing` KB exists with at least one compiled document, **When** an MCP client calls `list_kbs`, **Then** the response includes an entry for the `marketing` KB with its name and readiness indicator.
2. **Given** no KBs with completed documents exist, **When** an MCP client calls `list_kbs`, **Then** the response returns an empty list (not an error).

---

### User Story 3 — Ingest Marketing Documents Without Rate-Limit Failures (Priority: P3)

A developer sets up the local stack and runs a one-time ingestion script to populate the `marketing` KB from documents present in the `marketing_kb/` directory (which is gitignored). The ingestion completes successfully regardless of the number of documents, because it employs an exponential-backoff retry strategy with per-file throttling to avoid OpenAI 429 errors.

**Why this priority**: This is a prerequisite for testing the MCP tools end-to-end with real content. It is an operational/setup concern rather than a runtime user concern, hence P3.

**Independent Test**: Can be tested by running the ingestion script against the `marketing_kb/` directory with a real OpenAI key, verifying that all documents transition to `complete` status in the database without any permanent 429 failures.

**Acceptance Scenarios**:

1. **Given** the `marketing_kb/` directory contains multiple documents across subdirectories, **When** the ingestion script is executed, **Then** each document is submitted as a compilation job and eventually reaches `complete` status.
2. **Given** a 429 response is returned from OpenAI during compilation, **When** the retry strategy engages, **Then** the job is retried with exponential backoff (base 2s, max 60s, up to 5 attempts) and ultimately succeeds or is marked failed with a meaningful reason.
3. **Given** the `marketing_kb/` directory is absent or empty, **When** the ingestion script is run, **Then** it exits cleanly with an informative log message rather than an error.

---

### Edge Cases

- What happens when `ask_kb` is called with a `kb_id` that does not exist in the database? → MCP server returns a structured "not found" error with the unknown identifier.
- What happens when the KB exists but has no compiled documents (status not `complete`)? → MCP server returns a "KB not ready" error, prompting the user to wait for ingestion to complete.
- What happens when the question exceeds the maximum allowed length? → The MCP tool validates and rejects the input before forwarding to `generator-api`.
- What happens when multiple documents are ingested concurrently and the OpenAI rate limit is hit simultaneously? → The per-document semaphore and global rate-limiter serialise or throttle concurrent requests so at most N compilation threads run at once.
- What happens when an ingested file format is unsupported? → The ingestion script logs a warning and skips the file, continuing with remaining documents.
- What happens when the MCP server is restarted mid-query? → In-flight tool calls fail with a connection error; the MCP host is responsible for retry at the session level.

## Security, Observability, and Isolation Notes *(mandatory for features touching data or API)*

### Security Considerations

- Authentication/authorisation: Intentionally deferred for local development. The MCP server binds only within the Docker Compose network; no public exposure. Future iterations will add API-key or OAuth2 bearer token validation at the MCP layer.
- Input validation: All `ask_kb` and `list_kbs` tool arguments are validated via Pydantic v2 models before any downstream call is made; `kb_id` is accepted as UUID only; `question` length is capped at 8,000 characters (parity with `generator-api`).
- Secret handling: `LLM_API_KEY` is passed via env var only; it is never logged or surfaced in MCP tool responses.
- bandit findings: Bandit must pass with no HIGH or CRITICAL findings before merge; any necessary suppressions must include inline rationale.

### Observability Considerations

- Logging: Tool calls log at `INFO` level: tool name, KB identifier (not question text), and elapsed ms. Errors log at `ERROR` level with exception context.
- Metrics: No new Prometheus metrics in this iteration; existing `generator-api` metrics cover the downstream query path.
- Tracing: No distributed tracing in v1; correlation IDs are logged per-call for log-based tracing.
- Health/readiness impact: The `mcp-server` container exposes a `/health` endpoint that confirms it can reach `generator-api`; Docker Compose healthcheck depends on this endpoint.

### Isolation Considerations

- Per-customer data boundaries: The MCP server inherits KB-level isolation from `generator-api`; each query is scoped to a specific `kb_id`; no cross-KB leakage is possible.
- Process isolation: `mcp-server` runs as an independent container in the Compose network; it does not share scratch volumes with `compiler-worker`.
- Scratch/temp file cleanup: The MCP server holds no local state between tool calls; all state lives in `generator-api` and the database.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a FastMCP-based server that is launchable as a standalone service within the Docker Compose stack, reachable at a stable local port.
- **FR-002**: The MCP server MUST expose an `ask_kb` tool that accepts a natural-language question and a knowledge-base identifier, proxies the query to `generator-api`, and returns the answer with citations.
- **FR-003**: The MCP server MUST expose a `list_kbs` tool that returns all knowledge bases that have at least one document in `complete` status, without requiring any arguments from the caller.
- **FR-004**: The MCP server MUST NOT expose raw database, blob storage, or compilation management tools; its surface area is limited to read-only knowledge consumption.
- **FR-005**: All MCP tool inputs MUST be validated; invalid inputs MUST return structured error responses without crashing the server.
- **FR-006**: The `mcp-server` container MUST declare a Docker Compose `healthcheck` and all dependent services must await it being healthy before being considered ready.
- **FR-007**: The ingestion script MUST scan all supported document types (`.docx`, `.pptx`, `.pdf`, `.txt`, `.md`) recursively from the target directory, register them in the database, and enqueue compilation jobs.
- **FR-008**: The ingestion script MUST employ exponential-backoff retry logic for OpenAI 429 errors, with configurable base delay, maximum delay, and maximum retry count (defaults: base 2s, max 60s, 5 retries).
- **FR-009**: The ingestion script MUST serialize or throttle concurrent document submissions to avoid overwhelming the rate limit; a configurable concurrency ceiling (default: 3 parallel jobs) MUST be respected.
- **FR-010**: The `marketing_kb/` directory MUST be listed in `.gitignore`; no document content from it may ever be committed.
- **FR-011**: The MCP server MUST propagate `generator-api` error responses as structured MCP errors so MCP hosts can surface them intelligibly to users.
- **FR-012**: The MCP server MUST be reachable over both `stdio` transport (for local CLI/agent use) and SSE/HTTP transport (for networked MCP hosts such as Cursor or GitHub Copilot) to maximise compatibility with different host environments.

### Key Entities

- **Knowledge Base**: A named, versioned collection of compiled documents. Key attributes: unique identifier (UUID), human-readable slug/name, readiness status (ready when ≥1 document is `complete`).
- **MCP Tool**: A callable function exposed by the FastMCP server. Attributes: name, description, typed input schema, typed output schema.
- **Ingestion Job**: Represents a single document being submitted for compilation. Tracks file path, target KB, submission status, and retry count.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An MCP host configured against the running local stack can receive a grounded, citation-bearing answer to a marketing question in under 30 seconds end-to-end.
- **SC-002**: The `list_kbs` tool returns results in under 2 seconds with no documents as a lower bound.
- **SC-003**: All documents in `marketing_kb/` are ingested to `complete` status with zero permanent 429 failures when using the ingestion script with the rate-limit strategy engaged.
- **SC-004**: The `mcp-server` container starts and reports healthy within 30 seconds of the Compose stack coming up.
- **SC-005**: The MCP server toolset is limited to 2–3 tools; no tool causes excessive context bloat (each tool description is ≤150 words; input/output schemas are concise).
- **SC-006**: `ruff check`, `ruff format --check`, and `bandit -r .` all pass on the new code before the feature branch is merged.

## Assumptions

- The `generator-api` service is the canonical query engine; the MCP server delegates all knowledge retrieval to it rather than re-implementing any LLM or RAG logic directly.
- Documents in `marketing_kb/` are in formats already supported by `openkb-core` (`.docx`, `.pptx`, `.pdf`, `.txt`, `.md`); any other format will be skipped with a warning.
- The MCP server will be deployed as a Docker Compose service in local development; production deployment patterns (e.g., cloud-hosted MCP endpoint) are out of scope for this iteration.
- A single `marketing` KB is sufficient for the initial validation; multi-KB or multi-tenant scenarios are not in scope for this feature.
- Security (auth, TLS, tenant isolation at the MCP layer) is explicitly deferred to a future feature; this iteration targets a trusted local development environment only.
- The FastMCP library version will be pinned at the exact version used at implementation time and added to `pyproject.toml` with a rationale comment, consistent with project dependency management conventions.
- The `stdio` transport is the minimum viable transport for agent integration; SSE/HTTP transport is a stretch goal within this feature.
- `openkb-core` is consumed as a versioned pip dependency and is not modified in this repository; all new code lives in `mcp_server/` (a new top-level package) within this repository.

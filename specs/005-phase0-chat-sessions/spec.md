# Feature Specification: Phase 0 Chat Session Assembly

**Feature Branch**: `005-phase0-chat-sessions`
**Created**: 2026-06-21
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Start a new chat session (Priority: P1)

A developer or tester running OpenKB locally wants to start a multi-turn conversation with a knowledge base. They create a new session against a specific KB, send an opening question, and receive an answer grounded in the KB's content.

**Why this priority**: Creating a session and receiving a first response is the foundational interaction that all other chat behaviour depends on. Nothing else works without this.

**Independent Test**: Can be fully tested by POSTing to `/kbs/{kb_id}/chat/sessions` to create a session, then POSTing a message to that session and verifying an answer is returned. Delivers standalone value as a one-shot Q&A over a KB.

**Acceptance Scenarios**:

1. **Given** a knowledge base exists with indexed content, **When** a caller POSTs to `/kbs/{kb_id}/chat/sessions`, **Then** a new session is created and a unique `session_id` is returned with a `201 Created` response.
2. **Given** a newly created session, **When** a caller POSTs a message to `/kbs/{kb_id}/chat/sessions/{id}/messages`, **Then** a response is returned that answers the question using the KB's content, and both the user message and assistant response are persisted.
3. **Given** a valid `kb_id` that does not exist, **When** a caller attempts to create a session, **Then** a `404 Not Found` response is returned.
4. **Given** a session creation request with a missing or malformed `kb_id`, **When** the request is received, **Then** a `400 Bad Request` response is returned.

---

### User Story 2 — Continue a conversation across multiple turns (Priority: P1)

A developer validating multi-turn coherence sends a follow-up question in an existing session. The second answer demonstrably draws on the context established in the first turn — confirming that the session-assembly layer is correctly injecting history into each upstream query.

**Why this priority**: Multi-turn coherence is the entire purpose of Phase 0 chat. This validates the session-assembly logic — the core intellectual work of this feature. Without this, chat is indistinguishable from repeated one-shot queries.

**Independent Test**: Send turn 1: "What is PageIndex?". Send turn 2: "How is it used in this document?". The answer to turn 2 references PageIndex without the caller repeating what it is — demonstrating context carry-over.

**Acceptance Scenarios**:

1. **Given** a session with one completed exchange (user + assistant message), **When** a caller sends a follow-up message, **Then** the assembled context sent upstream includes the prior exchange, and the response reflects awareness of the earlier turn.
2. **Given** a session with many prior turns exceeding the configurable history window, **When** a new message is sent, **Then** only the most recent N turns are included in the assembled context (where N is the configured limit), preventing context overflow.
3. **Given** a session with one prior turn, **When** the second message is processed, **Then** both the new user message and the new assistant response are persisted to the message store, preserving the full conversation record.

---

### User Story 3 — Retrieve conversation history (Priority: P2)

A developer or front-end client wants to display the full message history for an existing session — for example to render a chat UI that shows all previous turns when a user returns to a session.

**Why this priority**: History retrieval is required for any UI that renders chat conversations. It is a read-only operation that does not affect the core assembly logic, making it independently deliverable.

**Independent Test**: After completing two or more turns in a session, perform a GET against `/kbs/{kb_id}/chat/sessions/{id}/messages` and verify all messages are returned in chronological order with correct role labels.

**Acceptance Scenarios**:

1. **Given** a session with two completed exchanges, **When** a caller GETs the message history, **Then** all four messages (two user, two assistant) are returned in chronological order, each with role, content, and timestamp.
2. **Given** a session with no messages yet, **When** a caller GETs the message history, **Then** an empty list is returned with a `200 OK` response.
3. **Given** a `session_id` that does not exist, **When** a caller GETs the message history, **Then** a `404 Not Found` response is returned.

---

### User Story 4 — List sessions for a knowledge base (Priority: P3)

A developer or operator wants to enumerate all chat sessions that have been started against a given KB — useful for debugging, auditing, and later as a foundation for session listing in a UI.

**Why this priority**: Useful for observability but not required for validating the core chat loop. Can be implemented as a thin read operation once sessions are being stored.

**Independent Test**: After creating two sessions against the same KB, perform a GET against `/kbs/{kb_id}/chat/sessions` and verify both sessions are listed with their metadata.

**Acceptance Scenarios**:

1. **Given** two sessions have been created for a KB, **When** a caller GETs `/kbs/{kb_id}/chat/sessions`, **Then** both sessions are returned with their `session_id`, `title`, and `created_at`.
2. **Given** no sessions exist for a KB, **When** a caller GETs the session list, **Then** an empty list is returned with a `200 OK` response.
3. **Given** the first message in a session has been sent, **When** the session is listed, **Then** the `title` field is populated with an auto-generated value derived from the first user message.

---

### Edge Cases

- What happens when the upstream `query` endpoint is unavailable or returns an error? The chat endpoint should propagate a meaningful error to the caller rather than silently failing or persisting a partial message.
- What happens when a message is sent to a session that belongs to a different KB than the URL specifies? The system must validate that `session_id` belongs to `kb_id` and return `404` or `403` if not.
- What happens when the message content is empty or consists only of whitespace? A `400 Bad Request` should be returned before any upstream call is made.
- What happens if the history window configuration is set to zero or a negative value? The system must treat this as invalid configuration and apply a safe default.
- What happens when the KB has no indexed content? The upstream query will return no results; the assistant response should still be persisted and returned (with an appropriate "no information found" message from the upstream layer).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a `POST /kbs/{kb_id}/chat/sessions` endpoint that creates a new chat session scoped to the specified knowledge base and returns a unique `session_id`.
- **FR-002**: The system MUST expose a `POST /kbs/{kb_id}/chat/sessions/{id}/messages` endpoint that accepts a user message, assembles conversation history, calls the upstream query endpoint with assembled context, persists the exchange, and returns the assistant response with any citations.
- **FR-003**: The system MUST expose a `GET /kbs/{kb_id}/chat/sessions/{id}/messages` endpoint that returns the full chronologically-ordered message history for a session.
- **FR-004**: The system MUST expose a `GET /kbs/{kb_id}/chat/sessions` endpoint that returns a list of all sessions for a given knowledge base, including session metadata (id, title, created_at).
- **FR-005**: When assembling context for an upstream query call, the system MUST include the most recent N turns of conversation history, where N is determined by a configurable limit designed to keep the assembled context within reasonable bounds.
- **FR-006**: The assembled context passed to the upstream query endpoint MUST include the prior conversation turns followed by the new user message, formatted in a way the upstream query endpoint can process as a single question.
- **FR-007**: The system MUST persist every user message and every assistant response (including citations) to durable storage immediately after each exchange completes.
- **FR-008**: Sessions MUST be keyed by `(kb_id, session_id)`. No user identity is required in Phase 0.
- **FR-009**: The session title MUST be auto-generated from the first user message in the session (e.g., a truncated version of the first message text).
- **FR-010**: The system MUST validate that the `session_id` in a message or history request belongs to the specified `kb_id`, returning an appropriate error if not.
- **FR-011**: The system MUST return a `404 Not Found` response when a request references a `kb_id` or `session_id` that does not exist.
- **FR-012**: The system MUST return a `400 Bad Request` response when a message request contains empty or whitespace-only content.
- **FR-013**: The chat endpoints MUST be implemented as an extension of the existing `generator-api` service — no new runtime service or container is required for Phase 0.
- **FR-014**: The durable store for sessions and messages MUST be the existing Postgres instance used by the rest of the Phase 0 stack. No additional caching layer is required for Phase 0.
- **FR-015**: Two new database tables — `chat_sessions` and `chat_messages` — MUST be introduced via a new database migration that builds on top of the existing Phase 0 schema (spec 001).

### Key Entities

- **Chat Session** (`chat_sessions`): Represents a single ongoing conversation between a caller and a knowledge base. Identified by a unique ID, scoped to a KB, carries an auto-generated title derived from the first message, and records creation/update timestamps. No user identity in Phase 0.
- **Chat Message** (`chat_messages`): A single turn in a conversation. Has a role (`user` or `assistant`), text content, and an optional set of source citations returned by the upstream query. Belongs to exactly one session and is immutable once written. Records a timestamp and an optional token cost for observability.
- **Knowledge Base** (`knowledge_bases`): Pre-existing entity (from spec 001). Chat sessions are scoped to a KB; the KB must exist before a session can be created against it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A two-turn conversation can be completed end-to-end — session creation, first message, second message — with the second answer demonstrably referencing context from the first turn, validating the session-assembly logic.
- **SC-002**: All four chat API endpoints respond correctly to both happy-path and error-path requests as defined by the acceptance scenarios in this specification.
- **SC-003**: The entire chat feature operates within the existing Docker Compose stack with no new infrastructure containers added. Starting the Phase 0 stack (`docker compose up`) is sufficient to run chat.
- **SC-004**: Message history for any session can be retrieved in full after the fact, confirming durable persistence of every exchange.
- **SC-005**: The history window limit is demonstrably enforced — a session with more turns than the configured limit does not include older turns in its assembled context.
- **SC-006**: The new database migration applies cleanly on top of the existing Phase 0 schema without requiring a full schema reset.

## Assumptions

- The upstream `query` endpoint (implemented in spec 003, `generator-api`) is functional and accepts a text question, returning a text answer with optional citations. The session-assembly layer treats it as a black box.
- A simple conversational history prefix format — such as prepending prior turns as labelled text before the new question — is sufficient for Phase 0 to demonstrate multi-turn coherence. A more sophisticated prompt-engineering approach is deferred to Phase 1.
- The configurable history window (number of prior turns to include) defaults to a small value (e.g., 10 turns) that comfortably fits within typical language model context limits; this value can be overridden via environment variable or configuration file.
- Python is the implementation language for `generator-api`, consistent with the rest of the OpenKB stack.
- Postgres is the only durable store needed for Phase 0 chat; Redis or any other caching/session-store technology is explicitly deferred.
- The `via` field on `chat_sessions` (indicating the client type, e.g., `web` or `mcp`) defaults to `web` for all Phase 0 sessions.
- No pagination is required on the message history or session list endpoints for Phase 0 given the expected low volume of local testing.
- Citation data from the upstream query response is stored as-is in the `citations` column of `chat_messages`; no transformation or validation of citation shape is performed by the session layer.
- The `deleted_at` column is included in the `chat_sessions` schema for forward-compatibility with Phase 1 soft-delete support, but no delete endpoint is implemented in Phase 0.

## Out of Scope

- User identity (`user_id`) on sessions — deferred to Phase 1 when an authentication and users table exists.
- Redis or any in-memory session cache — Postgres is the sole session store for Phase 0.
- Streaming responses — the assistant response is returned as a complete message only.
- Session deletion endpoint — the schema supports soft-delete via `deleted_at`, but no API surface for deletion is built in Phase 0.
- Session sharing between multiple users.
- MCP-driven chat — deferred to Phase 2.
- Rate limiting, quotas, or abuse prevention — no auth means no per-user controls in Phase 0.
- Front-end or UI — the API surface is the deliverable; no browser-based chat UI is in scope.

# Feature Specification: Delete Document Endpoint

**Feature Branch**: `feature/011-delete-document-endpoint`
**Created**: 2026-06-27
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Delete an Existing Document (Priority: P1)

A caller wants to remove a specific document from a knowledge base. After the deletion, the document should no longer appear in the knowledge base index, and any downstream consumers of the knowledge base should naturally stop seeing it. The operation must complete quickly, without triggering a full recompilation or any AI inference work.

**Why this priority**: This is the core capability of the feature. All other stories are edge cases around it.

**Independent Test**: Can be fully tested by sending a `DELETE` request for a known document and verifying the response is `204`, the document is no longer listed in the index, and the document's summary blob is gone from storage.

**Acceptance Scenarios**:

1. **Given** a knowledge base exists with at least one compiled document, **When** a caller sends `DELETE /kbs/{kb_id}/documents/{doc_id}`, **Then** the response is `204 No Content` with an empty body.
2. **Given** the deletion succeeded, **When** downstream consumers (compiler worker, MCP server) next process the knowledge base, **Then** they do not include the deleted document in their results.
3. **Given** the deletion succeeded, **When** the knowledge base index is inspected, **Then** the deleted document is absent and all remaining non-deleted completed documents are still listed.
4. **Given** a deletion request is processed, **Then** no AI/LLM calls are made and the operation completes in under 5 seconds under normal conditions.

---

### User Story 2 — Repeat Deletion is Safe (Priority: P2)

A caller sends a `DELETE` request for a document that has already been deleted. The system must respond gracefully without error, returning the same success response as the first call. This allows callers to use the endpoint without needing to track whether a document has been previously deleted.

**Why this priority**: Idempotency is a fundamental API contract requirement that prevents caller-side retry logic from causing errors.

**Independent Test**: Can be tested independently by calling `DELETE` twice for the same document ID and confirming both responses are `204`.

**Acceptance Scenarios**:

1. **Given** a document has already been deleted, **When** a caller sends `DELETE /kbs/{kb_id}/documents/{doc_id}` again, **Then** the response is `204 No Content`.
2. **Given** the second deletion call, **Then** the knowledge base index is not corrupted or re-rebuilt unnecessarily in a harmful way.

---

### User Story 3 — Delete a Document from a Non-Existent Knowledge Base (Priority: P3)

A caller references a knowledge base ID that does not exist (or has itself been soft-deleted). The system must return a clear, machine-readable error.

**Why this priority**: Error cases need to be clearly communicated, but are secondary to the primary success path.

**Independent Test**: Can be tested by sending a `DELETE` request with a random UUID as `kb_id` and verifying a `404` error response.

**Acceptance Scenarios**:

1. **Given** a `kb_id` that does not exist, **When** a caller sends `DELETE /kbs/{kb_id}/documents/{doc_id}`, **Then** the response is `404 Not Found` with a descriptive error message.
2. **Given** a `doc_id` that does not exist within a valid `kb_id`, **When** a caller sends the delete request, **Then** the response is `404 Not Found` with a descriptive error message.

---

### Edge Cases

- What happens if the document's summary blob is already absent from storage at deletion time? The operation should still succeed — the soft-delete and index rebuild proceed normally; a missing blob is treated as already gone.
- What happens if the index rebuild fails after the soft-delete? The document is already soft-deleted so downstream consumers will ignore it; the failure should be surfaced as a 5xx error so the caller is aware the index may be stale.
- What happens if both `kb_id` and `doc_id` are valid UUIDs but the document does not belong to that knowledge base? The response must be `404` — the system must not delete a document that lives under a different knowledge base.
- What if multiple concurrent callers attempt to delete the same document simultaneously? The soft-delete operation must be idempotent at the database level; both callers should receive `204`.

## Security, Observability, and Isolation Notes *(mandatory for features touching data or API)*

### Security Considerations

- Authentication/authorisation: Out of scope for this feature. The endpoint is unauthenticated in this iteration. This is an explicit, documented constraint.
- Input validation: Both `kb_id` and `doc_id` are UUID path parameters; FastAPI's UUID type coercion rejects non-UUID values with a `422` response before any handler logic runs.
- Secret handling: No new secrets introduced. Storage credentials are sourced from existing environment configuration, consistent with the rest of `generator_api`.
- bandit findings: No new security-sensitive code patterns are introduced (no `eval`, no shell execution, no subprocess calls). The delete blob operation uses the existing container client pattern already reviewed in `blob.py`.

### Observability Considerations

- Logging: The service layer must log at `INFO` level when a document is soft-deleted (include `kb_id`, `doc_id`, `doc_slug`), when the summary blob is deleted, and when the index rebuild completes. Log at `WARNING` if the summary blob was not found (already absent). Log at `ERROR` if the index rebuild or blob operations fail.
- Metrics: No new Prometheus metrics required for this feature.
- Tracing: No distributed tracing spans added in this iteration.
- Health/readiness impact: None. The endpoint does not affect the `/health` or `/ready` probes.

### Isolation Considerations

- Per-customer data boundaries: The service layer must verify that the `doc_id` belongs to the `kb_id` in the same query that resolves the document row — a document from another knowledge base must not be deletable via a mismatched `kb_id`.
- Process isolation: No new sidecar or worker processes are introduced.
- Scratch/temp file cleanup: No scratch files are created by this operation; the endpoint only performs database writes and blob storage operations.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a `DELETE /kbs/{kb_id}/documents/{doc_id}` HTTP endpoint.
- **FR-002**: On receiving a valid delete request, the system MUST mark the target document as deleted in the database by recording the deletion timestamp. The document record is retained; no hard delete occurs.
- **FR-003**: The system MUST delete the document's summary blob artifact from the knowledge base's storage container. The blob path is derived from the document's slug.
- **FR-004**: Concept and entity blobs associated with the document MUST NOT be deleted.
- **FR-005**: After marking the document as deleted, the system MUST rebuild and re-upload the knowledge base index to reflect only the remaining non-deleted, completed documents.
- **FR-006**: The index rebuild MUST NOT invoke any AI or language model services.
- **FR-007**: The endpoint MUST return `204 No Content` on successful deletion.
- **FR-008**: The endpoint MUST be idempotent: if the target document is already deleted, the endpoint MUST return `204 No Content` without performing any additional storage or database operations beyond confirming the document exists.
- **FR-009**: If the `kb_id` does not exist (or is itself deleted), the system MUST return `404 Not Found`.
- **FR-010**: If the `doc_id` does not exist within the specified `kb_id`, the system MUST return `404 Not Found`.
- **FR-011**: All business logic (database updates, blob operations, index rebuild) MUST be delegated to a service function; the route handler must contain no business logic.
- **FR-012**: The service layer MUST raise typed custom exceptions (`KBNotFoundError`, `DocumentNotFoundError`) that are translated to HTTP responses by exception handlers or the route handler.

### Key Entities

- **Document**: A single piece of content within a knowledge base. Has a unique identifier, a knowledge-base association, a human-readable slug used to derive blob storage paths, a compilation status, and a soft-delete timestamp.
- **Knowledge Base**: The parent container for documents. Identified by a UUID. Has its own soft-delete state; a delete request against a deleted knowledge base must return `404`.
- **Summary Blob**: The storage artefact for a document's compiled summary. Named using the document's slug and scoped under the knowledge base's storage prefix. Deleted as part of the document removal.
- **Knowledge Base Index**: A generated manifest listing all non-deleted completed documents within a knowledge base. Rebuilt and re-uploaded automatically as part of every document deletion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A delete request for an existing document completes and returns `204 No Content` in under 5 seconds under normal load, excluding network transit time.
- **SC-002**: After a successful deletion, the knowledge base index no longer references the deleted document and correctly lists all remaining non-deleted completed documents.
- **SC-003**: Sending the same delete request twice in succession always yields `204 No Content` on both attempts.
- **SC-004**: Sending a delete request for an unknown knowledge base or unknown document consistently yields `404 Not Found` within the same response-time budget as a successful deletion.
- **SC-005**: Zero AI/LLM calls are made during any document deletion operation, verifiable by inspecting service logs and confirming no model invocation entries appear.
- **SC-006**: The feature has automated test coverage for the success path, the idempotent repeat-deletion path, and all defined error paths (unknown knowledge base, unknown document, mismatched ownership); all tests pass consistently.

## Assumptions

- The `documents` table already has a `deleted_at` nullable timestamp column and a `slug` text column, as specified in the codebase context.
- Downstream services (`compiler_worker`, `mcp_server`) already filter out rows where `deleted_at IS NOT NULL`, so soft-deleting a document is sufficient to hide it from all consumers without additional coordination.
- The summary blob path convention `{kb_id}/summaries/{doc_slug}.md` is stable and does not require dynamic resolution beyond reading the `slug` field from the document row.
- The existing blob container client and index-rebuild utilities in `generator_api/blob.py` can be reused without modification for this feature.
- Authentication and authorisation are deferred; no caller identity or permission checks are required in this iteration.
- The `DocumentNotFoundError` exception class does not yet exist in `generator_api/exceptions.py` and must be added as part of this feature's implementation.
- Only the summary blob is removed on deletion; concepts and entity blobs are intentionally preserved as they may be shared across documents or are inexpensive to retain.

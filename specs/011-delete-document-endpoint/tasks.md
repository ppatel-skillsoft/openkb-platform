---
description: "Task list for Feature 011 — Delete Document Endpoint"
---

# Tasks: Delete Document Endpoint (Feature 011)

**Feature Branch**: `feature/011-delete-document-endpoint`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Contract**: [contracts/delete-document.md](contracts/delete-document.md)
**Generated**: 2026-06-27

**Input**: `specs/011-delete-document-endpoint/` — spec.md (required), plan.md (required),
data-model.md, contracts/delete-document.md, research.md, quickstart.md

---

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no inter-task dependency within the phase)
- **[Story]**: User story label — [US1], [US2], [US3] (maps to spec.md priority order)
- File paths are relative to the repository root

---

## Phase 1: Setup (Test Scaffold)

**Purpose**: Create the test directory structure and empty module/skeleton files that all later phases depend on.
No production code is written here.

- [ ] T001 Create `tests/unit/generator_api/__init__.py` as an empty module marker (directory already exists; this file is absent)
- [ ] T002 [P] Create `tests/integration/generator_api/__init__.py` — first create the `tests/integration/generator_api/` directory, then add the empty module marker
- [ ] T003 [P] Create `tests/integration/generator_api/conftest.py` with an `AsyncClient` app fixture that calls `create_app()` via `ASGITransport`, and stub `app.dependency_overrides` entries for `get_db` (returns an `AsyncMock` session) and `get_settings` (returns a mock settings object); include a fixture that patches `service_delete_document` at the import boundary using `unittest.mock.AsyncMock`
- [ ] T004 [P] Create `tests/unit/generator_api/test_blob_helpers.py` with empty placeholder stubs (pass bodies) for: `test_delete_summary_blob_success`, `test_delete_summary_blob_already_gone`, `test_delete_summary_blob_azure_error`, `test_upload_index_to_blob_success`, `test_upload_index_to_blob_azure_error`
- [ ] T005 [P] Create `tests/unit/generator_api/test_service.py` with empty placeholder stubs (pass bodies) for: `test_delete_success`, `test_delete_idempotent`, `test_delete_kb_not_found`, `test_delete_doc_not_found`, `test_delete_cross_kb_mismatch`, `test_delete_blob_already_absent`
- [ ] T006 [P] Create `tests/integration/generator_api/test_delete_document.py` with empty placeholder stubs (pass bodies) for: `test_delete_returns_204`, `test_delete_idempotent_204`, `test_delete_kb_not_found_404`, `test_delete_doc_not_found_404`, `test_delete_invalid_uuid_422`

**Checkpoint**: All test files importable; `uv run pytest --collect-only` finds all stubs with no import errors.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Exception class and blob helper functions that the service layer (Phase 3) depends on.
No user-story work can begin until this phase is complete.

**CRITICAL**: `DocumentNotFoundError` and both blob helpers must exist before `service.py` can be written.

- [ ] T007 Add `DocumentNotFoundError(doc_id: str, kb_id: str)` class to `generator_api/exceptions.py` — store `self.doc_id` and `self.kb_id` as attributes; `super().__init__(f"Document {doc_id} not found in knowledge base {kb_id}")`; mirror the structure of the existing `KBNotFoundError`; add `from __future__ import annotations` if not already present
- [ ] T008 Add async `delete_summary_blob(connection_string: str, container: str, doc_slug: str) -> None` to `generator_api/blob.py` — constructs blob name `wiki/summaries/{doc_slug}.md`; uses `BlobServiceClient.from_connection_string` context manager; swallows `ResourceNotFoundError` silently (blob already gone is not an error); wraps all other Azure SDK exceptions in `BlobSyncError`; add `from __future__ import annotations` guard if absent
- [ ] T009 Add async `upload_index_to_blob(connection_string: str, container: str, index_path: Path) -> None` to `generator_api/blob.py` — reads `index_path` from disk and uploads its contents to blob name `wiki/index.md` within `container`; overwrites any existing blob; wraps Azure SDK exceptions in `BlobSyncError`; follows the same `BlobServiceClient` context-manager pattern as `delete_summary_blob`
- [ ] T010 Implement all five unit test stubs in `tests/unit/generator_api/test_blob_helpers.py` — mock `BlobServiceClient` via `unittest.mock.patch`; for `delete_summary_blob`: (1) blob exists → no error, (2) `ResourceNotFoundError` raised → silent success, (3) other `AzureError` raised → `BlobSyncError` surfaced; for `upload_index_to_blob`: (4) success path → blob uploaded with correct name `wiki/index.md`, (5) `AzureError` raised → `BlobSyncError` surfaced

**Checkpoint**: `uv run pytest tests/unit/generator_api/test_blob_helpers.py` passes (5/5). Foundation ready — user-story phases can now begin.

---

## Phase 3: User Story 1 — Delete an Existing Document (Priority: P1) 🎯 MVP

**Goal**: A caller sends `DELETE /kbs/{kb_id}/documents/{doc_id}` for a known, active document and receives `204 No Content`. The document row is soft-deleted, the summary blob is removed, and the KB index is rebuilt.

**Independent Test**: Send `DELETE` for a known document via `httpx.AsyncClient`; assert response status is `204`, mock verifies `service_delete_document` was called once with the correct UUIDs.

- [ ] T011 [US1] Create `generator_api/service.py` with `async def service_delete_document(kb_id: str, doc_id: str, db: AsyncSession, connection_string: str) -> None` — (1) query `knowledge_bases` with `id = kb_id AND deleted_at IS NULL`; raise `KBNotFoundError(kb_id)` if no row; (2) query `documents` with `id = doc_id AND kb_id = kb_id`; raise `DocumentNotFoundError(doc_id, kb_id)` if no row; (3) if `doc.deleted_at is not None` return immediately (idempotency guard — placeholder, fully implemented in T016); (4) execute `UPDATE documents SET deleted_at = timezone('utc', NOW()) WHERE id = doc_id`; (5) call `delete_summary_blob(connection_string, container, doc.slug)`; (6) in a `tempfile.mkdtemp` scratch dir (cleaned in `finally`): call `sync_wiki_tree(connection_string, container, scratch_dir)`, `rebuild_index_md(scratch_dir)`, `upload_index_to_blob(connection_string, container, index_path)`; (7) log `INFO` on soft-delete (include `kb_id`, `doc_id`, `doc.slug`), `WARNING` if blob was already absent, `INFO` on index rebuild; use `logging.getLogger(__name__)`; add `from __future__ import annotations`
- [ ] T012 [P] [US1] Add `DELETE /kbs/{kb_id}/documents/{doc_id}` route to `generator_api/router.py` — path parameters typed as `uuid.UUID`; inject `db: AsyncSession = Depends(get_db)` and `settings: Settings = Depends(get_settings)`; call `await service_delete_document(str(kb_id), str(doc_id), db, settings.azure_storage_connection_string)`; return `Response(status_code=204)`; no business logic in the handler body
- [ ] T013 [P] [US1] Register `DocumentNotFoundError → 404` exception handler in `generator_api/app.py` — add `@app.exception_handler(DocumentNotFoundError)` returning `JSONResponse(status_code=404, content={"detail": str(exc)})`; import `DocumentNotFoundError` from `generator_api.exceptions`; place alongside the existing `KBNotFoundError` handler
- [ ] T014 [P] [US1] Implement unit tests for the success path and blob-already-absent edge case in `tests/unit/generator_api/test_service.py` — mock `AsyncSession` with `AsyncMock` returning a valid KB row and active doc row; mock `delete_summary_blob`, `upload_index_to_blob`, `sync_wiki_tree`, `rebuild_index_md`; assert (1) `deleted_at` is set via the UPDATE call, (2) `delete_summary_blob` called with correct container + slug, (3) `upload_index_to_blob` called once; second test: mock `delete_summary_blob` to raise `ResourceNotFoundError` (already absent) — assert service still completes and calls `upload_index_to_blob`
- [ ] T015 [US1] Add integration tests for the `204` success path and `422` invalid-UUID path to `tests/integration/generator_api/test_delete_document.py` — use `httpx.AsyncClient` with `ASGITransport`; for success: mock `service_delete_document` to return `None`, assert response status `204` and empty body; for invalid UUID: send a non-UUID path parameter, assert response status `422` with FastAPI validation error body; no mock needed for the 422 case

**Checkpoint**: `uv run pytest tests/unit/generator_api/test_service.py tests/integration/generator_api/test_delete_document.py -k "success or 204 or invalid"` passes. User Story 1 endpoint is functional.

---

## Phase 4: User Story 2 — Repeat Deletion is Safe (Priority: P2)

**Goal**: Calling `DELETE` a second time for an already-deleted document returns `204 No Content` immediately, with no storage operations performed.

**Independent Test**: Mock service to return `None` on both calls; assert both responses are `204`. Unit test verifies no blob or DB calls when `deleted_at` is already set.

- [ ] T016 [US2] Complete the idempotency guard in `generator_api/service.py` — after the ownership query in `service_delete_document`, if the fetched `doc.deleted_at is not None`: log `INFO` ("document already deleted, returning early"), and `return` immediately without executing the UPDATE, `delete_summary_blob`, `sync_wiki_tree`, or `upload_index_to_blob` calls; this replaces the placeholder stub left in T011 step (3)
- [ ] T017 [P] [US2] Implement the `test_delete_idempotent` unit test in `tests/unit/generator_api/test_service.py` — mock the `documents` query to return a row where `deleted_at` is already set to a UTC timestamp; assert `delete_summary_blob` is **not** called, `upload_index_to_blob` is **not** called, and no DB UPDATE is executed; assert service returns `None` without raising
- [ ] T018 [P] [US2] Implement the `test_delete_idempotent_204` integration test in `tests/integration/generator_api/test_delete_document.py` — mock `service_delete_document` to return `None` on both invocations; send `DELETE` twice for the same path; assert both responses are `204 No Content`

**Checkpoint**: `uv run pytest tests/ -k "idempotent"` passes (2 tests). User Story 2 satisfied.

---

## Phase 5: User Story 3 — Delete from a Non-Existent KB or Unknown Document (Priority: P3)

**Goal**: Requests referencing an unknown `kb_id` or an unknown/mismatched `doc_id` return `404 Not Found` with a descriptive `{"detail": "..."}` body.

**Independent Test**: Mock service to raise `KBNotFoundError` or `DocumentNotFoundError`; assert response is `404` with correct detail message.

- [ ] T019 [P] [US3] Implement the `test_delete_kb_not_found`, `test_delete_doc_not_found`, and `test_delete_cross_kb_mismatch` unit tests in `tests/unit/generator_api/test_service.py` — for KB not found: mock `knowledge_bases` query to return `None`; assert `KBNotFoundError` is raised with the correct `kb_id`; for doc not found: mock KB query to return a valid row but `documents` query to return `None`; assert `DocumentNotFoundError` is raised with the correct `doc_id` and `kb_id`; for cross-KB mismatch: same setup as doc not found (ownership check enforced by `id = doc_id AND kb_id = kb_id` returning `None`); assert `DocumentNotFoundError` raised
- [ ] T020 [P] [US3] Implement the `test_delete_kb_not_found_404` and `test_delete_doc_not_found_404` integration tests in `tests/integration/generator_api/test_delete_document.py` — configure mock `service_delete_document` to `side_effect=KBNotFoundError(kb_id)` for the first test and `side_effect=DocumentNotFoundError(doc_id, kb_id)` for the second; assert response status `404` and `response.json()["detail"]` contains the relevant ID

**Checkpoint**: `uv run pytest tests/ -k "not_found or 404"` passes (5 tests). All three user stories are independently functional.

---

## Phase 6: Polish and Cross-Cutting Concerns

**Purpose**: Edge-case hardening, observability verification, and quality-gate sign-off across all modified files.

- [ ] T021 Add `BlobSyncError` zero-blob edge-case handler to `generator_api/service.py` — in the index-rebuild block of `service_delete_document`, catch `BlobSyncError`; if the exception message contains `"no blobs found"` (sentinel from `blob.py`), write an empty-section `index.md` file to the scratch dir (four empty sections: Documents, Concepts, Entities, Explorations) and call `upload_index_to_blob`; re-raise for any other `BlobSyncError` message; log `WARNING` on the empty-KB path; log `ERROR` on the re-raise path
- [ ] T022 [P] Verify observability completeness in `generator_api/service.py` — confirm the module-level logger is declared as `logger = logging.getLogger(__name__)`; confirm `INFO` is logged after the `deleted_at` UPDATE (include `kb_id`, `doc_id`, `doc_slug`); confirm `WARNING` is logged when `delete_summary_blob` silently skips a missing blob; confirm `INFO` is logged after `upload_index_to_blob` completes; confirm `ERROR` is logged before re-raising a non-empty `BlobSyncError`; confirm no `print()` calls anywhere in new or modified files
- [ ] T023 [P] Run `uv run ruff check .` and `uv run ruff format --check .` from the repository root — resolve any findings in `generator_api/exceptions.py`, `generator_api/blob.py`, `generator_api/service.py`, `generator_api/router.py`, `generator_api/app.py`, and all new test files; both commands must exit with code `0`
- [ ] T024 [P] Run `uv run bandit -r generator_api/ tests/` — confirm zero new findings introduced by this feature; pay attention to any `B101` (assert usage in tests is expected), `B603`/`B607` (no subprocess calls expected), and ensure no `eval` or shell execution patterns were introduced

**Checkpoint**: All 24 tasks complete. `uv run pytest` passes. `ruff` and `bandit` exit clean. Feature ready for PR against `develop`.

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)       ──────────────────────────────► T001, T002, T003, T004, T005, T006
Phase 2 (Foundational)  depends on Phase 1 ──────────► T007, T008 → T009, T010
Phase 3 (US1)           depends on Phase 2 completion ► T011 → T012║T013║T014 → T015
Phase 4 (US2)           depends on T011 ─────────────► T016 → T017║T018
Phase 5 (US3)           depends on T011, T013 ────────► T019║T020
Phase 6 (Polish)        depends on Phases 3, 4, 5 ───► T021 → T022║T023║T024
```

### Task-Level Dependencies

| Task | Depends On | Reason |
|------|-----------|--------|
| T003 | T002 | `tests/integration/generator_api/` directory must exist |
| T006 | T002 | Same directory requirement |
| T008 | T001 (Phase 1 done) | `blob.py` edits begin after scaffold complete |
| T009 | T008 | Sequential addition to the same `blob.py` file |
| T010 | T008, T009 | Tests need both helpers to exist |
| T011 | T007, T008, T009 | `service.py` imports `DocumentNotFoundError`, `delete_summary_blob`, `upload_index_to_blob` |
| T012 | T011 | Route imports `service_delete_document` |
| T013 | T007 | Handler imports `DocumentNotFoundError` |
| T014 | T011 | Tests mock `service_delete_document` |
| T015 | T012, T013 | Integration test needs registered route + exception handler |
| T016 | T011 | Amends `service_delete_document` |
| T017 | T016 | Tests the idempotency guard added in T016 |
| T018 | T015 | Extends integration test file; needs route/handler wired |
| T019 | T011 | Tests error-raise branches in `service_delete_document` |
| T020 | T013, T015 | Needs `DocumentNotFoundError` handler registered; builds on test infra |
| T021 | T011 | Amends `service_delete_document` edge-case block |
| T022 | T011, T021 | Audit logging after all service edits are final |
| T023 | all implementation tasks | Quality gate on final code |
| T024 | all implementation tasks | Security gate on final code |

### User Story Independence

- **US1 (P1)**: Can start as soon as Phase 2 is complete — no dependency on US2 or US3 tests
- **US2 (P2)**: Can start as soon as T011 (service.py) is complete — idempotency guard is a two-line addition
- **US3 (P3)**: Can start as soon as T011 + T013 are complete — not-found raises are already in the service; this phase only adds test coverage

---

## Parallel Execution Examples

### Phase 1 — All Scaffold Files in Parallel (after T001+T002)

```bash
# Run in parallel — all different files, no dependencies between them:
Task: "Create tests/integration/generator_api/conftest.py"       # T003
Task: "Create tests/unit/generator_api/test_blob_helpers.py"     # T004
Task: "Create tests/unit/generator_api/test_service.py"          # T005
Task: "Create tests/integration/generator_api/test_delete_document.py"  # T006
```

### Phase 3 — US1 Implementation after T011

```bash
# Run in parallel — all different files, no inter-dependencies:
Task: "Add DELETE route to generator_api/router.py"              # T012
Task: "Register exception handler in generator_api/app.py"       # T013
Task: "Write success-path unit tests in test_service.py"         # T014
```

### Phase 6 — Quality Gates in Parallel (after T021+T022)

```bash
# Run in parallel:
Task: "uv run ruff check . && uv run ruff format --check ."      # T023
Task: "uv run bandit -r generator_api/ tests/"                   # T024
```

---

## Implementation Strategy

### MVP First (User Story 1 Only — ~6 tasks after setup)

1. Complete Phase 1 (T001–T006) — scaffold
2. Complete Phase 2 (T007–T010) — exceptions + blob helpers
3. Complete Phase 3 (T011–T015) — service, route, handler, tests
4. **STOP and VALIDATE**: `uv run pytest tests/unit/generator_api/ tests/integration/generator_api/`
5. Manual smoke test via `quickstart.md` steps 5a–5c against local Docker Compose

### Incremental Delivery

1. **Phase 1 + 2 → Phase 3**: Core delete with 204 + 422 responses → demo-ready MVP
2. **+ Phase 4**: Idempotent repeat delete covered → SC-003 satisfied
3. **+ Phase 5**: 404 error paths covered → SC-004 satisfied and all of SC-006
4. **+ Phase 6**: Edge-case hardening + quality gates → PR-ready

### Single-Developer Sequence

```
T001 → T002 → T003–T006 (parallel) →
T007 → T008 → T009 → T010 →
T011 → T012 (parallel) → T013 (parallel) → T014 (parallel) → T015 →
T016 → T017 (parallel) → T018 (parallel) →
T019 (parallel) → T020 (parallel) →
T021 → T022 (parallel) → T023 (parallel) → T024 (parallel)
```

---

## Notes

- **No migrations needed**: `deleted_at` and `slug` columns already exist on `documents` and `knowledge_bases`; see `data-model.md`
- **Blob path**: `wiki/summaries/{doc_slug}.md` within container `kb-{kb_id}` (or `storage_container_path`); confirmed in `research.md` §1
- **`upload_index_to_blob`**: new function; no equivalent exists in `generator_api/blob.py` today; see `research.md` §4
- **Zero-blob edge case** (T021): after all docs in a KB are deleted, `sync_wiki_tree` raises `BlobSyncError("... no blobs found ...")`; handle separately from unexpected storage errors — `research.md` §3
- **Auth deferred**: endpoint is unauthenticated in this iteration; explicitly documented in spec §Security
- **[P] marker**: tasks sharing the same file are never marked [P] even if phased sequentially (T008→T009, T014→T017→T019, T015→T018→T020)

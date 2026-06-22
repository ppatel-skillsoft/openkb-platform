# Implementation Plan: Phase 0 Sidecar Isolation Validation

**Branch**: `feature/006-sidecar-isolation-validation` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/006-sidecar-isolation-validation/spec.md`

## Summary

Build a **pure test harness** — no new services, no new API endpoints, no new database tables — that proves the Phase 0 exit criterion: two concurrent jobs against two different knowledge bases, each with their own sidecar instance, never cross-contaminate. The suite asserts five isolation properties (scratch directory isolation, port isolation, process state isolation, sequential reuse safety, concurrent query isolation) against the Docker Compose stack already defined by specs 001–004. All five scenarios run locally via `docker compose run --rm isolation-tests` or `pytest tests/isolation/` with no real Azure services required. Azurite replaces Azure Blob Storage; a local Postgres and Redis complete the stack. Two minimal KB fixtures (KB-A: astronomy content, KB-B: botany content) with topically distinct documents make cross-contamination detectable in citations and file paths. All isolation assertions are programmatic — inspecting filesystem paths, OS port bindings, process tables, and HTTP response payloads — not just observational absence of errors.

## Technical Context

**Language/Version**: Python 3.12 (matches `pyproject.toml` `requires-python = ">=3.12""`)  
**Primary Dependencies**: pytest 9.0.3, pytest-asyncio, asyncpg, httpx, azure-storage-blob SDK, psutil  
**Storage**: PostgreSQL (asyncpg for seeding KB/document fixtures), Azurite (azure-storage-blob SDK for seeding compiled wiki blobs)  
**Testing**: pytest with pytest-asyncio — this feature **is** the test harness; no unit tests required  
**Target Platform**: Linux / macOS Docker Compose environment (Windows out of scope per spec assumptions)  
**Project Type**: Integration test harness (pytest test suite + Docker Compose service profile)  
**Performance Goals**: Full suite completes in < 10 minutes on a standard developer machine (SC-002)  
**Constraints**: Local-first hard requirement — no real Azure services; no changes to any service code from specs 001–004; all five scenarios runnable with a single command  
**Scale/Scope**: 2 KB fixtures × 5 isolation scenarios; pairwise isolation is the Phase 0 scope

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **Note**: The project constitution (`.specify/memory/constitution.md`) is currently a template with placeholder content — no project-specific principles have been ratified yet. Constitutional gates cannot be evaluated against placeholder text. This plan proceeds on the basis of the feature spec requirements alone, which are self-consistent and carry no observable violations. The constitution should be populated before Phase 1 implementation begins.

| Gate | Status | Notes |
|------|--------|-------|
| No new service code changes | ✅ PASS | Spec explicitly prohibits changes to specs 001–004 services |
| No new API endpoints | ✅ PASS | Test harness only — no new HTTP routes |
| No new database tables | ✅ PASS | Reads existing schema; no migrations |
| Local-first (no real Azure) | ✅ PASS | Azurite + local Postgres + local Redis only |
| Single command invocation | ✅ PASS | `docker compose run --rm isolation-tests` or `pytest tests/isolation/` |
| Assertions are programmatic | ✅ PASS | psutil, filesystem inspection, HTTP content assertions required by FR-006 |

**Post-design re-check**: No violations introduced by Phase 1 design. The scratch volume mount decision (see research.md §4) does not require service code changes — it is a Compose configuration addition only.

## Project Structure

### Documentation (this feature)

```text
specs/006-sidecar-isolation-validation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── RUNBOOK.md           # Operational runbook (FR-018, FR-019)
├── contracts/
│   ├── test-invocation.md      # How to invoke the suite; env vars; exit codes
│   └── kb-fixture-schema.md    # KB-A and KB-B fixture definitions
└── tasks.md             # Phase 2 output (/speckit.tasks — not created by /speckit.plan)
```

### Source Code (repository root)

```text
tests/
└── isolation/
    ├── conftest.py                          # Session fixtures: DB seed, blob seed, Compose readiness
    ├── fixtures/
    │   ├── kb_a/
    │   │   └── astronomy-intro.md           # KB-A: astronomy content (topic: stars & planets)
    │   └── kb_b/
    │       └── botany-intro.md              # KB-B: botany content (topic: plants & photosynthesis)
    ├── helpers/
    │   ├── __init__.py
    │   ├── process_helpers.py               # wait_for_http(), assert_port_bound(), assert_proc_dead()
    │   └── blob_helpers.py                  # seed_wiki_blobs(), list_kb_blobs()
    ├── test_scratch_directory_isolation.py  # Scenario 1 (FR-007, FR-008)
    ├── test_port_isolation.py               # Scenario 2 (FR-009, FR-010, FR-011)
    ├── test_process_state_isolation.py      # Scenario 3 (FR-012, FR-013)
    ├── test_sequential_reuse_safety.py      # Scenario 4 (FR-014, FR-015)
    └── test_concurrent_query_isolation.py   # Scenario 5 (FR-016, FR-017)

# Additions to existing files:
docker-compose.yml                           # New `isolation-tests` service (profile: test)
tests/isolation/Dockerfile                   # Python 3.12-slim + test deps
```

**Structure Decision**: Pure test harness — all deliverables go under `tests/isolation/`. No `src/` tree is created. The Docker Compose `isolation-tests` service is added under a `test` profile so it does not affect `docker compose up` for normal development. The shared scratch volume (`compiler_scratch`) is the only Compose addition that touches existing service configuration (compiler-worker gains a `volumes:` entry pointing to the named volume); this is not a service code change.

## Complexity Tracking

> No constitution violations to justify — the constitution is a placeholder. No complexity anomalies detected.

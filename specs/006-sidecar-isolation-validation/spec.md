# Feature Specification: Sidecar Isolation Validation Suite

**Feature Branch**: `006-sidecar-isolation-validation`
**Created**: 2026-06-21
**Status**: Draft

## Overview

This spec covers the **Phase 0 exit criterion** that proves the sidecar-per-job isolation assumption holds before multi-tenancy can be built. It is not a new service, API, or migration — it is an automated validation suite that asserts five isolation properties across two concurrent knowledge bases, all runnable locally via Docker Compose.

The safety model for OpenKB Enterprise depends entirely on one premise: each sidecar instance is fully isolated from every other. This suite proves that premise in practice, not just in design.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Scratch Directory Isolation (Priority: P1)

A developer runs the validation suite and receives a deterministic pass/fail result confirming that two concurrent compilation jobs for different knowledge bases never read from or write to each other's working directories.

**Why this priority**: Shared scratch directories are the most direct path to corrupted output — wrong pages attributed to the wrong knowledge base. This is the most fundamental isolation property and must pass before any other scenario is meaningful.

**Independent Test**: Run only the scratch-directory isolation scenario against a minimal two-KB fixture. The test passes if each job's scratch directory is created exclusively for that job, contains only that job's files, and is not visible to the concurrent job at any point during or after execution.

**Acceptance Scenarios**:

1. **Given** two compilation jobs for KB-A and KB-B are started concurrently, **When** both jobs are running simultaneously, **Then** each job's scratch directory contains only that job's source files and neither job can list or access the other's directory.
2. **Given** a compilation job for KB-A has completed, **When** the scratch directory for KB-A is inspected, **Then** it contains no files originating from KB-B.
3. **Given** a compilation job for KB-A has completed and its sidecar has been torn down, **When** the scratch directory state is checked, **Then** the directory has been fully cleaned up and no residual files remain.

---

### User Story 2 — Port Isolation (Priority: P1)

A developer runs the validation suite and receives a deterministic pass/fail result confirming that two concurrently running sidecar processes bind to different ports and that HTTP traffic sent to one sidecar is never received by the other.

**Why this priority**: Port collision causes one sidecar's HTTP traffic to be routed to a different knowledge base's sidecar, which is a direct data-leakage path. This must hold before concurrent query serving is safe.

**Independent Test**: Run only the port-isolation scenario. The test passes if each sidecar reports a distinct bound address, and an HTTP request directed at KB-A's sidecar endpoint returns a response that originated from KB-A's sidecar (not KB-B's).

**Acceptance Scenarios**:

1. **Given** two sidecar instances are started concurrently (one for KB-A, one for KB-B), **When** both are fully initialised, **Then** each reports a distinct port or socket address with no overlap.
2. **Given** an HTTP request is sent to KB-A's sidecar endpoint, **When** a response is received, **Then** the response contains content from KB-A only, and KB-B's sidecar has not processed the request.
3. **Given** a port is reused by a new sidecar after the previous sidecar on that port has been torn down, **When** the new sidecar starts, **Then** the previous sidecar is confirmed fully terminated before the new one binds.

---

### User Story 3 — Process State Isolation (Priority: P2)

A developer runs the validation suite and receives a deterministic pass/fail result confirming that a sidecar started for KB-B has no access to the in-memory state, wiki tree, or compiled context of a previously run sidecar for KB-A.

**Why this priority**: Process state leakage causes wrong answers with wrong citations — a subtle failure that is harder to detect than a crash. It must be proven absent before query results can be trusted in a multi-KB environment.

**Independent Test**: Run only the process-state isolation scenario. The test passes if KB-B's sidecar, after being started on a host where KB-A's sidecar previously ran, returns responses that cite only KB-B's documents.

**Acceptance Scenarios**:

1. **Given** KB-A's sidecar has compiled a set of documents, **When** KB-A's sidecar is torn down and KB-B's sidecar is started on the same worker host, **Then** KB-B's sidecar has no access to KB-A's wiki tree or compiled artefacts.
2. **Given** a query is issued against KB-B's freshly started sidecar, **When** a response is returned, **Then** the response contains citations only from KB-B's document set, with zero citations from KB-A's documents.

---

### User Story 4 — Sequential Reuse Safety (Priority: P2)

A developer runs the validation suite and receives a deterministic pass/fail result confirming that after KB-A's job completes and its sidecar is torn down, a subsequent job for KB-B that happens to be assigned the same OS port produces no contamination from the prior run.

**Why this priority**: Port number reuse by the OS is normal and unavoidable. The validation must confirm that OS-level port reuse does not create a logical isolation gap between sequential jobs.

**Independent Test**: Run only the sequential-reuse scenario. The test passes if the prior sidecar is confirmed dead before the next one starts, the scratch directory for the prior job is fully removed, and the new job's output contains no artefacts from the prior job.

**Acceptance Scenarios**:

1. **Given** KB-A's job has completed and its sidecar has been torn down, **When** a new job for KB-B is started and the OS assigns the same port number that KB-A's sidecar previously used, **Then** there is no process listening on that port from the prior run at the moment KB-B's sidecar binds.
2. **Given** KB-A's scratch directory existed during its job, **When** KB-B's job starts in the same sequence, **Then** KB-A's scratch directory has been deleted and KB-B's job has no path that overlaps with where KB-A's directory was.

---

### User Story 5 — Concurrent Query Isolation (Priority: P2)

A developer runs the validation suite and receives a deterministic pass/fail result confirming that two concurrent query requests against different knowledge bases each use their own sidecar and wiki tree checkout, and neither response contains citations from the other KB's documents.

**Why this priority**: This is the query-time analogue of the compilation-time isolation. It validates the `generator-api` path specifically — the user-facing query path that will be exposed to real users in Phase 1.

**Independent Test**: Run only the concurrent-query isolation scenario. The test passes if two simultaneous query requests — one against KB-A, one against KB-B — each return responses whose citations are exclusively sourced from their respective knowledge bases.

**Acceptance Scenarios**:

1. **Given** two query requests are issued concurrently (one against KB-A, one against KB-B), **When** both responses are received, **Then** KB-A's response contains only KB-A citations and KB-B's response contains only KB-B citations.
2. **Given** both query requests are processing simultaneously, **When** each sidecar's wiki tree checkout is inspected, **Then** each checkout contains only the documents of its respective knowledge base.
3. **Given** both query requests have completed, **When** both sidecars are torn down, **Then** no residual wiki tree or process state from either request is detectable on the host.

---

### Edge Cases

- What happens when a sidecar fails to start? The test harness must detect the failure, report it clearly, and not proceed with isolation assertions that depend on that sidecar being live.
- What happens when a scratch directory cleanup fails? The suite must report the failure and flag it as a blocking issue rather than silently leaving residual state.
- What happens when the OS assigns the same port to two concurrent sidecars? The suite must detect the collision and report it as an isolation failure (the port-assignment mechanism must prevent this).
- What happens when both KB fixtures contain a document with the same filename? The isolation assertions must still hold — same-named files in different KBs must not be conflated.
- What happens if a sidecar process does not terminate within the expected teardown window? The suite must flag this as a hanging process and report it as an isolation failure.

---

## Requirements *(mandatory)*

### Functional Requirements

**Test Harness**

- **FR-001**: The validation suite MUST be runnable with a single command against the existing Docker Compose stack (e.g., `docker compose run isolation-tests` or `pytest tests/isolation/`).
- **FR-002**: The suite MUST require no real cloud services — it MUST use only local substitutes (Azurite for blob storage, local Postgres, the upstream sidecar image).
- **FR-003**: The suite MUST exercise all five isolation scenarios: scratch directory isolation, port isolation, process state isolation, sequential reuse safety, and concurrent query isolation.
- **FR-004**: Each scenario MUST produce an unambiguous pass or fail result with a human-readable explanation of what was checked and what failed.
- **FR-005**: The suite MUST use two minimal but real knowledge-base fixtures (KB-A and KB-B), each containing at least one distinct document with distinct content, so that cross-contamination is detectable.
- **FR-006**: The suite MUST assert isolation properties programmatically — inspecting directory listings, port bindings, process tables, and response payloads — not just rely on absence of visible errors.

**Scratch Directory Isolation**

- **FR-007**: The suite MUST verify, while both compilation jobs are running concurrently, that each job's scratch directory path is unique and contains only that job's files.
- **FR-008**: The suite MUST verify that after a job completes, its scratch directory has been removed and no residual files remain accessible on the host.

**Port Isolation**

- **FR-009**: The suite MUST verify that two concurrently running sidecar processes are bound to different ports or socket addresses.
- **FR-010**: The suite MUST verify that an HTTP request directed at KB-A's sidecar endpoint returns a response from KB-A's sidecar and not KB-B's, by asserting on response content that is distinct between the two KBs.
- **FR-011**: The suite MUST verify that before a new sidecar binds to any port, no prior sidecar process is still listening on that port.

**Process State Isolation**

- **FR-012**: The suite MUST verify that a sidecar started for KB-B, after KB-A's sidecar has been torn down on the same host, has no read access to KB-A's compiled artefacts or wiki tree.
- **FR-013**: The suite MUST verify that a query issued to KB-B's sidecar returns zero citations from KB-A's document set.

**Sequential Reuse Safety**

- **FR-014**: The suite MUST verify that KB-A's sidecar process is fully terminated before KB-B's sidecar starts, even when the OS assigns the same port number to both.
- **FR-015**: The suite MUST verify that KB-A's scratch directory is deleted before KB-B's job begins.

**Concurrent Query Isolation**

- **FR-016**: The suite MUST issue two query requests simultaneously and verify that each response contains only citations from its respective knowledge base.
- **FR-017**: The suite MUST verify that each concurrent query request has its own isolated wiki tree checkout — the two checkouts MUST NOT share any file path prefix.

**Runbook**

- **FR-018**: A runbook MUST be provided documenting how to run the validation suite manually, how to interpret pass/fail output, and what remediation steps apply to each type of failure.
- **FR-019**: The runbook MUST document the exact commands required to run the full suite and each individual scenario in isolation.

### Key Entities

- **Isolation Test Scenario**: One of the five named isolation properties being validated; has a name, a set of setup steps, a set of assertion steps, and a pass/fail outcome.
- **KB Fixture**: A minimal, self-contained knowledge base used exclusively for testing; has a unique identifier (e.g., KB-A, KB-B) and at least one document with content distinct from all other fixtures.
- **Sidecar Instance**: A running instance of the upstream sidecar process; characterised by its bound address, associated scratch directory path, and lifecycle state (starting / running / torn down).
- **Scratch Directory**: A temporary working directory allocated exclusively to one sidecar instance for one job or request; must be unique, non-overlapping with any concurrent scratch directory, and removed after the job completes.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five isolation scenarios produce a pass result when run against the Docker Compose stack on a clean developer machine with no prior state.
- **SC-002**: The full validation suite completes end-to-end in under 10 minutes on a standard developer machine, including fixture setup and teardown.
- **SC-003**: Each failing scenario produces a failure message that identifies the specific isolation property violated, the two knowledge bases involved, and the evidence of cross-contamination, enabling a developer to diagnose the root cause without additional tooling.
- **SC-004**: A developer with no prior context on the isolation model can run the suite and interpret the results using only the runbook, without needing to read implementation code.
- **SC-005**: The suite can be re-run on the same machine immediately after a first run (i.e., teardown is complete and no residual state blocks a subsequent run).
- **SC-006**: No scenario produces a false positive — a passing result MUST mean isolation genuinely holds, not that the assertion was too weak to detect a violation.
- **SC-007**: The suite is accepted by a reviewer as sufficient proof that sidecar isolation holds, enabling sign-off on the Phase 0 exit criterion.

---

## Assumptions

- The Docker Compose stack from specs 001–004 is already operational; this suite adds a new service/profile to that stack rather than replacing it.
- The upstream sidecar image is available locally (pulled or built) prior to running the suite; the suite does not manage image builds.
- The `compiler-worker` (spec 002) and `generator-api` (spec 003) sidecar spin-up/teardown logic already implements the isolation model — this suite validates that implementation, it does not create a new one.
- Python with pytest is the established test harness technology for this project; the suite is authored in Python/pytest.
- Two KB fixtures are sufficient to prove pairwise isolation; testing N>2 concurrent KBs is out of scope for Phase 0.
- "Same wiki output" and "same answer quality" have already been validated by specs 002 and 003; this suite focuses exclusively on isolation between concurrent KBs, not on output correctness.
- No real Azure services (Blob Storage, etc.) are required; Azurite is an acceptable substitute for all blob operations in the test fixtures.
- The suite runs on Linux or macOS (the environments where Docker Compose is available); Windows support is not required for Phase 0.

---

## Out of Scope

- Performance or load testing (Phase 5)
- Security penetration testing (Phase 4)
- Network-level container isolation (deployment/Kubernetes concern)
- Testing isolation between different organisations' data (requires Phase 1 multi-tenancy)
- Testing more than two concurrent knowledge bases (pairwise is sufficient for Phase 0)
- Any changes to existing service code in specs 001–004
- Any new API endpoints or database tables

# Research: Phase 0 Sidecar Isolation Validation

**Feature**: 006-sidecar-isolation-validation  
**Phase**: 0 — Research & unknowns resolution  
**Date**: 2026-06-21

---

## §1 — How to assert scratch directory isolation programmatically

**Question**: How do we verify, while two compiler-worker jobs are running concurrently, that each job's scratch directory contains only that job's files and neither can see the other's directory?

**Decision**: Use a named Docker volume (`compiler_scratch`) mounted read-only into the `isolation-tests` container alongside the `compiler-worker` container. The test harness directly reads the volume's filesystem to enumerate directory paths and file contents mid-run, then asserts non-overlap. After job completion the test asserts the directory is absent (worker's own cleanup, per FR-008).

**Rationale**: Direct filesystem inspection is the most reliable assertion method — it is not subject to race conditions in log scraping or API polling. The named volume approach requires zero service code changes: only Compose configuration changes (adding a `volumes:` reference on both `compiler-worker` and `isolation-tests`). All existing compiler-worker scratch-directory behaviour is unchanged.

**Alternatives considered**:
- *Docker API inspection via Docker socket*: feasible but more complex; `docker exec` into the compiler-worker container would work but is slower and creates a dependency on the container name. Rejected in favour of direct volume mount which is simpler and faster.
- *Compiler-worker debug API endpoint*: would require a service code change, which is explicitly prohibited by the spec. Rejected.
- *Log scraping*: non-deterministic timing, no guarantees about log completeness mid-run. Rejected.

---

## §2 — How to assert port isolation programmatically

**Question**: How do we prove that an HTTP request to KB-A's sidecar port never reaches KB-B's sidecar?

**Decision**: Use `psutil.net_connections()` to assert that the two sidecar processes are bound to distinct ports, then use `httpx.AsyncClient` to send a targeted HTTP request to each port and assert on response content. The sidecar's `/health` or equivalent endpoint is expected to return the KB identifier in its response body (or we use the `/init` response, which echoes the wiki path). If the sidecar has no KB-identifying field, we use the scratch directory path embedded in the sidecar's response headers or body as the discriminator.

**Rationale**: Two separate assertions are necessary: (1) a structural assertion via `psutil` that the ports differ, and (2) a traffic-routing assertion via HTTP that content from KB-A's port is KB-A's content. The structural assertion alone does not prove isolation; the content assertion alone does not prove the ports differ. Both are required by FR-009 and FR-010.

**Alternatives considered**:
- *Network namespace inspection*: too low-level for Python; requires privileged container access. Rejected.
- *Wireshark/tcpdump packet capture*: excessive complexity for a pytest harness. Rejected.

---

## §3 — How to assert process state isolation programmatically

**Question**: After KB-A's sidecar is torn down, how do we prove KB-B's freshly started sidecar has no access to KB-A's wiki tree or compiled artefacts?

**Decision**: Use two complementary assertions:
1. **Filesystem assertion**: verify that KB-A's scratch directory path does not exist (or is empty) when KB-B's sidecar starts, using direct volume filesystem inspection (§1 approach).
2. **Query-response citation assertion**: issue a query to KB-B's sidecar whose answer would necessarily cite KB-A content if process state leaked (e.g., ask about stars when KB-B is botany-only). Assert that the response citations contain zero references to any KB-A document path. The KB-A and KB-B fixture documents use topically distinct content (astronomy vs. botany) so a false-positive pass from an empty citation list is distinguishable from a genuine content response with correct citations.

**Rationale**: Process state isolation is inherently about what the sidecar _can access_, not just what it _chooses to return_. Filesystem assertion covers the "can access" dimension; citation assertion covers the "does return" dimension. Both are required because a sidecar could theoretically have in-memory cached state without filesystem residue.

**Alternatives considered**:
- *Checking /proc/{pid}/maps*: too OS-specific and requires elevated privileges. Rejected.
- *Injecting a known "poison" document into KB-A and checking it does not appear in KB-B responses*: this is exactly what the citation assertion does — the astronomy docs are the "poison" content for KB-B. Adopted.

---

## §4 — Shared scratch volume: Compose configuration strategy

**Question**: What is the minimal Compose change to give the test container direct read access to the compiler-worker's scratch directory?

**Decision**: Add a named volume `compiler_scratch` to the Compose file:
```yaml
volumes:
  compiler_scratch:

services:
  compiler-worker:
    volumes:
      - compiler_scratch:/scratch    # existing SCRATCH_DIR env var should point here
  isolation-tests:
    volumes:
      - compiler_scratch:/scratch:ro  # read-only mount for assertions
```
The compiler-worker's `SCRATCH_DIR_ROOT` environment variable already points to `/scratch` (or equivalent) by convention from spec 002. No code change is needed — only the Compose volume declaration is new.

**Rationale**: Named volumes are Compose-native, require no host path hardcoding, survive container restarts, and cleanly scope the shared filesystem. The `:ro` flag on the test container prevents accidental interference with the worker's scratch operations.

**Alternatives considered**:
- *Bind mount to host path*: introduces host path dependency and makes the test non-portable. Rejected.
- *Copy files out via `docker cp`*: too slow for mid-run concurrent assertions. Rejected.

---

## §5 — KB fixture content strategy: making cross-contamination detectable

**Question**: What content should KB-A and KB-B fixture documents contain to make citation cross-contamination unambiguous?

**Decision**:
- **KB-A** (`kb_a/astronomy-intro.md`): ~300-word markdown document about stellar classification and planetary formation. Key distinguishing terms: "main sequence stars", "red giants", "planetary nebula", "Hertzsprung-Russell diagram".
- **KB-B** (`kb_b/botany-intro.md`): ~300-word markdown document about plant cell biology and photosynthesis. Key distinguishing terms: "chloroplast", "photosynthesis", "stomata", "xylem", "phloem".
- Query for Scenario 3 and 5: KB-B is queried with "What is photosynthesis?" — a question KB-B can answer correctly, but if KB-A state leaked, astronomy terms would appear in citations. KB-A is queried with "What is a main sequence star?" for the symmetric assertion.
- Filenames are intentionally different (`astronomy-intro.md` vs `botany-intro.md`) and also intentionally share a common suffix (`-intro.md`) to test that same-suffix matching does not cause incorrect conflation (edge case from spec).

**Rationale**: Topically orthogonal content ensures that any citation cross-contamination is immediately obvious — no astronomy term should appear in a botany KB response and vice versa. The content is long enough to produce at least one compiled wiki page per KB (required by FR-005) but short enough to compile quickly (< 2 minutes per KB, supporting the 10-minute total budget).

**Alternatives considered**:
- *Random UUID content*: not realistic; sidecars may handle non-prose poorly. Rejected.
- *Same topic, different details*: cross-contamination harder to detect in citation text. Rejected.

---

## §6 — Process termination assertion: confirming sidecar is fully dead

**Question**: How do we confirm that a sidecar process is fully terminated (not just signalled) before the next scenario asserts on port reuse?

**Decision**: Use `psutil.pid_exists(pid)` combined with `psutil.Process(pid).status() != psutil.STATUS_ZOMBIE` as the readiness gate. After the compiler-worker sends SIGTERM to a sidecar and waits, the test harness polls `psutil.pid_exists` with a configurable timeout (default: 5 seconds, configurable via `SIDECAR_TEARDOWN_TIMEOUT_SECONDS` env var) before proceeding with port-reuse assertions in Scenario 4.

**Rationale**: A process that has exited but not yet been waited on by its parent exists as a zombie and its PID is still technically "in use" from the kernel's perspective. The zombie check ensures the test does not produce a false pass by asserting on a port that is technically released but whose PID entry still exists.

**Alternatives considered**:
- *`os.waitpid(pid, 0)`*: only valid for direct child processes; the sidecar is a child of the compiler-worker, not of the test harness. Rejected.
- *Poll the port directly with `socket.connect`*: confirms the port is released but not that the process itself is dead. Insufficient for FR-014. Adopted as a complementary assertion, not the primary one.

---

## §7 — pytest-asyncio mode and fixture scoping

**Question**: What pytest-asyncio mode and fixture scope strategy should the isolation suite use?

**Decision**:
- **asyncio_mode = "auto"** in `pytest.ini` section of `pyproject.toml` (added for `tests/isolation/` only via a `conftest.py`-level marker or a separate `pytest.ini` in `tests/isolation/`). This avoids decorating every async test function individually.
- **Session-scoped fixtures**: Postgres seed (KB rows + document rows), Azurite blob seed (wiki page blobs), Docker Compose readiness probe. These are expensive and shared across all five scenarios.
- **Function-scoped fixtures**: per-test scratch directory state assertions, per-test sidecar process lifecycle (start → assert → teardown). Each test is responsible for starting and tearing down its own sidecar(s) via the compiler-worker job queue, so function scope is the right boundary.
- **Module-scoped fixtures**: none required.

**Rationale**: Session scope for infrastructure (Postgres, Azurite, Compose readiness) minimises setup overhead and keeps total suite time under the 10-minute budget. Function scope for process/filesystem state ensures tests are independent and the suite is re-runnable without residual state (SC-005).

**Alternatives considered**:
- *Class-based test organisation*: not standard in this project (existing `tests/` uses module-level functions). Rejected for consistency.
- *All session-scoped*: test ordering would become important; a sidecar left running by one test would interfere with another. Rejected.

---

## §8 — Single-command invocation: two entry points, one behaviour

**Question**: How do we satisfy both `docker compose run --rm isolation-tests` and `pytest tests/isolation/` as valid entry points?

**Decision**: The `isolation-tests` Compose service runs `pytest tests/isolation/ -v --tb=short` as its `CMD`. When running `pytest tests/isolation/` directly (outside Docker), the `conftest.py` session fixture detects environment variables and either asserts they are set (failing fast with a clear message) or falls back to localhost defaults for the case where the developer has started the Compose stack separately and is running pytest against it from their host. The environment variable `ISOLATION_ENV=docker` is set in the Compose service definition to distinguish the two modes.

**Rationale**: Developers iterating locally need `pytest tests/isolation/` to work without rebuilding the test container. The Compose entry point is for CI and clean-machine validation. Sharing the same test code for both requires only a small environment-detection shim in `conftest.py`.

**Alternatives considered**:
- *Separate test files for Docker vs. local*: code duplication, maintenance burden. Rejected.
- *Makefile target*: useful addition but not sufficient to satisfy FR-001 (single command). Supplementary only.

---

## §9 — Contracts from prior specs: what the test harness depends on

The following contracts from prior plans are exercised (but not owned) by this test harness. They are referenced as read-only inputs. If these contracts are not yet implemented, the isolation suite will fail with a clear dependency error from the session fixture.

| Contract | Source Spec | What the harness depends on |
|----------|-------------|----------------------------|
| Sidecar HTTP API (`/init`, `/add`, `/status`, `/query`) | spec 002 + spec 003 | Port isolation (§2) and process state isolation (§3) assert on HTTP responses |
| Sidecar spawn protocol (port assignment, scratch dir path) | spec 002 | Scratch dir isolation (§1) requires knowing the scratch dir naming convention |
| Blob storage paths (`kb-{id}/wiki/`) | spec 002 | Azurite fixture seeding uses this path prefix |
| Job queue message schema (KB ID, document blob path) | spec 002 | conftest.py enqueues jobs via Redis using this schema |
| DB session factory | spec 001 | conftest.py seeds `knowledge_bases` and `documents` rows |

> **Note**: These contracts are described in the prompt as planned artefacts. At time of writing, the contract documents do not yet exist on disk. The implementation tasks for this spec must include a prerequisite check that compiler-worker and generator-api are functional before running the isolation suite.

---

## Resolved unknowns summary

| Unknown | Resolution |
|---------|-----------|
| How to inspect scratch dirs mid-run? | Named Docker volume, read-only mount in test container (§4) |
| How to prove port routing, not just port difference? | HTTP content assertion on distinct KB content (§2) |
| How to detect process state leakage? | Filesystem absence + citation content assertion (§3) |
| How to confirm process is fully dead (not zombie)? | psutil pid_exists + status != zombie (§6) |
| Fixture content for detectable cross-contamination? | Astronomy vs. botany, topically orthogonal (§5) |
| pytest-asyncio strategy? | asyncio_mode=auto, session fixtures for infra, function for process lifecycle (§7) |
| Two entry points, same code? | ISOLATION_ENV env var + localhost fallback in conftest.py (§8) |

# RUNBOOK: Sidecar Isolation Validation Suite

**Feature**: 006-sidecar-isolation-validation  
**Date**: 2026-06-21  
**Audience**: Any developer running or diagnosing the Phase 0 exit-criterion validation

---

## Purpose

This runbook is the single reference for running, interpreting, diagnosing, and signing off on the sidecar isolation validation suite. A developer with no prior context on the isolation model MUST be able to run the suite and understand the results using only this document (SC-004).

---

## Table of Contents

1. [How to run the suite](#1-how-to-run-the-suite)
2. [What a passing run looks like](#2-what-a-passing-run-looks-like)
3. [What a failure looks like and what it means](#3-what-a-failure-looks-like-and-what-it-means)
4. [Diagnosis guide: by scenario](#4-diagnosis-guide-by-scenario)
5. [Common infrastructure failures](#5-common-infrastructure-failures)
6. [How to reset and re-run](#6-how-to-reset-and-re-run)
7. [Sign-off criteria](#7-sign-off-criteria)
8. [Escalation](#8-escalation)

---

## 1 — How to run the suite

### Full suite (single command)

```bash
# Ensure the stack is running first
docker compose up -d postgres azurite redis compiler-worker generator-api

# Wait for healthy state (check with: docker compose ps)

# Run the full isolation validation
docker compose run --rm isolation-tests
```

### Single scenario (for targeted diagnosis)

```bash
docker compose run --rm isolation-tests pytest tests/isolation/test_<scenario>.py -v --tb=long
```

Replace `<scenario>` with one of:
- `test_scratch_directory_isolation`
- `test_port_isolation`
- `test_process_state_isolation`
- `test_sequential_reuse_safety`
- `test_concurrent_query_isolation`

### Without Docker (developer iteration)

```bash
export POSTGRES_URL="postgresql://postgres:postgres@localhost:5432/openkb"
export AZURITE_BLOB_ENDPOINT="http://localhost:10000/devstoreaccount1"
export REDIS_URL="redis://localhost:6379/0"
export GENERATOR_API_BASE_URL="http://localhost:8001"
export COMPILER_WORKER_SCRATCH_ROOT="/tmp/openkb-scratch"

pytest tests/isolation/ -v --tb=short
```

---

## 2 — What a passing run looks like

```
================================ test session starts =================================
platform linux -- Python 3.12.x, pytest-9.0.3, asyncio_mode=auto
rootdir: /app, configfile: tests/isolation/pytest.ini

tests/isolation/test_scratch_directory_isolation.py::test_concurrent_scratch_dirs_are_unique PASSED
tests/isolation/test_scratch_directory_isolation.py::test_kba_scratch_contains_only_kba_files PASSED
tests/isolation/test_scratch_directory_isolation.py::test_scratch_dir_cleaned_after_job PASSED
tests/isolation/test_port_isolation.py::test_concurrent_sidecars_bind_different_ports PASSED
tests/isolation/test_port_isolation.py::test_http_to_kba_port_returns_kba_content PASSED
tests/isolation/test_port_isolation.py::test_http_to_kbb_port_returns_kbb_content PASSED
tests/isolation/test_port_isolation.py::test_no_prior_sidecar_on_port_before_new_bind PASSED
tests/isolation/test_process_state_isolation.py::test_kbb_scratch_dir_absent_when_kbb_sidecar_starts PASSED
tests/isolation/test_process_state_isolation.py::test_kbb_query_returns_zero_kba_citations PASSED
tests/isolation/test_sequential_reuse_safety.py::test_kba_proc_dead_before_kbb_starts PASSED
tests/isolation/test_sequential_reuse_safety.py::test_kba_scratch_deleted_before_kbb_job PASSED
tests/isolation/test_concurrent_query_isolation.py::test_concurrent_queries_return_own_citations_only PASSED

======================== 12 passed in 487.3s (0:08:07) ==============================
```

**Interpretation**: All 12 assertions across 5 scenarios passed. Sidecar isolation holds. The suite took 8 minutes 7 seconds — within the 10-minute budget.

This output is sufficient for Phase 0 sign-off.

---

## 3 — What a failure looks like and what it means

### Example: Port isolation failure

```
FAILED tests/isolation/test_port_isolation.py::test_concurrent_sidecars_bind_different_ports

    AssertionError: KB-A and KB-B sidecars bound to the same port
    KB-A pid=12345 port=54321
    KB-B pid=12346 port=54321   ← SAME PORT

    This means: the compiler-worker's dynamic port assignment logic
    assigned the same port to two concurrent sidecars. An HTTP request
    to port 54321 would be received by whichever sidecar happened to
    bind first — the other sidecar would fail to start or would steal
    the port on a subsequent attempt.

    Fix required: compiler-worker port assignment must not reuse a port
    that is currently bound by a live sidecar. See diagnosis §4.2.
```

### Example: Citation cross-contamination failure

```
FAILED tests/isolation/test_concurrent_query_isolation.py::test_concurrent_queries_return_own_citations_only

    AssertionError: KB-B response contains KB-A topic keyword 'red giant'
    KB-B query: "What is photosynthesis?"
    KB-B citations: ["kb-aaaaaaaa-.../wiki/concepts/stellar-classification.md"]
                                  ↑ This is a KB-A blob path — cross-contamination confirmed

    This means: the generator-api (or the sidecar it started) for KB-B
    served content from KB-A's wiki tree. The scratch directory for KB-B
    was not properly isolated from KB-A's compiled pages.

    Fix required: generator-api wiki sync must download only the
    storage_container_path for the requested kb_id. See diagnosis §4.5.
```

### General failure anatomy

Every failure message includes:
1. **Which assertion failed** — the test name and assert statement
2. **Observed value** — what the harness actually found
3. **Expected value** — what isolation requires
4. **Which KB IDs were involved** — identifies which side of the pairwise check failed
5. **Plain-English explanation** — what the failure means for isolation

---

## 4 — Diagnosis guide: by scenario

### 4.1 — Scratch directory isolation failures

**Symptom**: `test_concurrent_scratch_dirs_are_unique` fails — both KBs have the same or overlapping scratch path.

**Likely cause**: The compiler-worker generates scratch paths using a non-unique scheme (e.g., only using `kb_id` without a `job_id` component, causing the same path for two jobs submitted in rapid succession for the same KB, or a static path template with no unique discriminator).

**Diagnosis steps**:
1. Check the compiler-worker logs: `docker compose logs compiler-worker --tail=50`
2. Look for the scratch directory paths logged when each job starts
3. Verify the path template includes both `kb_id` and a unique `job_id` or UUID component
4. If paths are unique in logs but the test volume shows them as equal, verify the `SCRATCH_DIR_ROOT` env var matches the volume mount path

**Symptom**: `test_scratch_dir_cleaned_after_job` fails — scratch directory still exists after job completion.

**Likely cause**: The compiler-worker's teardown step (FR-012 from spec 002) did not run — either because the job failed silently, the teardown is conditional on success-only, or a container crash prevented cleanup.

**Diagnosis steps**:
1. Check `documents` table in Postgres: `SELECT id, status, failure_reason FROM documents WHERE kb_id IN (kba_id, kbb_id) ORDER BY updated_at DESC LIMIT 4;`
2. If `status = 'failed'`, the worker caught an error but teardown should still have run (spec 002 FR-012: "regardless of success or failure")
3. Check compiler-worker logs for teardown confirmation messages
4. If no teardown log: the worker may have a bug in its finally/cleanup block

---

### 4.2 — Port isolation failures

**Symptom**: `test_concurrent_sidecars_bind_different_ports` fails.

**Likely cause**: The compiler-worker's dynamic port selection reused a port already bound by a concurrently running sidecar. This happens when the "find a free port" logic uses `socket.bind((host, 0))` and then immediately closes the socket before starting the sidecar — another sidecar can grab the same ephemeral port in the window between socket close and sidecar startup.

**Diagnosis steps**:
1. Check compiler-worker source: does it use `SO_REUSEADDR` or does it hold the socket open during sidecar startup?
2. Run: `docker exec compiler-worker ss -tlnp | grep sidecar` during a concurrent job run to observe the actual bindings
3. Look for `port collision` log lines from the compiler-worker

**Symptom**: `test_http_to_kba_port_returns_kba_content` fails — KB-A port returns KB-B content.

**Likely cause**: Port assignment was correct but the test's port–KB mapping is wrong (test bug), or the sidecar is not loading the correct wiki tree from its scratch directory.

**Diagnosis steps**:
1. Verify the test reads the port from the correct sidecar's reported bound address (not hardcoded)
2. Check the sidecar startup arguments: does the KB-A sidecar point at KB-A's scratch directory?
3. Issue a manual HTTP request during a test run: `curl -s http://compiler-worker:<port>/health`

---

### 4.3 — Process state isolation failures

**Symptom**: `test_kbb_scratch_dir_absent_when_kbb_sidecar_starts` fails — KB-A's scratch directory still exists when KB-B's sidecar starts.

**Likely cause**: The compiler-worker did not clean up KB-A's scratch directory before starting KB-B's job (violates spec 002 FR-012 and FR-013).

**Diagnosis steps**:
1. Check if KB-A's job completed successfully: query `documents` table
2. Inspect the scratch volume directly: `docker run --rm -v compiler_scratch:/scratch alpine ls /scratch/`
3. Check compiler-worker logs for cleanup confirmation after KB-A's job

**Symptom**: `test_kbb_query_returns_zero_kba_citations` fails.

**Likely cause**: The generator-api synced the wrong wiki tree for KB-B — either it downloaded KB-A's blob path or it used a shared/cached scratch directory rather than a fresh one.

**Diagnosis steps**:
1. Check the generator-api logs for the wiki sync operation: which blob path was downloaded?
2. Inspect the generator-api scratch directory during the test: is it pointed at `storage_container_path` for KB-B only?
3. Check the `knowledge_bases.storage_container_path` for KB-B in Postgres: is it correct?

---

### 4.4 — Sequential reuse safety failures

**Symptom**: `test_kba_proc_dead_before_kbb_starts` fails — KB-A's sidecar PID still shows as alive when KB-B's job begins.

**Likely cause**: The compiler-worker's SIGTERM handling is not blocking — it sends the signal but does not wait for the process to fully exit before marking the job done and accepting the next job.

**Diagnosis steps**:
1. Check compiler-worker source: does it call `proc.wait()` (or `await proc.wait()` async) after `proc.terminate()`?
2. Check for zombie processes: `docker exec compiler-worker ps aux | grep Z`
3. Increase `SIDECAR_TEARDOWN_TIMEOUT_SECONDS` to 30 seconds for debugging: `docker compose run --rm -e SIDECAR_TEARDOWN_TIMEOUT_SECONDS=30 isolation-tests pytest tests/isolation/test_sequential_reuse_safety.py -v`

**Symptom**: `test_kba_scratch_deleted_before_kbb_job` fails.

**Likely cause**: Same as §4.3 scratch cleanup failure. See above.

---

### 4.5 — Concurrent query isolation failures

**Symptom**: `test_concurrent_queries_return_own_citations_only` fails.

**Likely cause** (in order of likelihood):
1. **Shared scratch directory**: generator-api uses a single global scratch path (e.g., `/tmp/wiki`) instead of a per-request unique path, causing KB-A's wiki files to overwrite KB-B's or vice versa mid-request
2. **Wrong blob path**: generator-api reads `storage_container_path` from Postgres correctly but downloads into the same local directory for all requests, conflating content
3. **Citation passthrough bug**: generator-api modifies or enriches citations with data from a previous request's sidecar response

**Diagnosis steps**:
1. Inspect generator-api logs: look for two concurrent requests and verify each shows a different scratch directory path
2. Check the generator-api implementation of FR-004 (per-request scratch directory) from spec 003
3. Use `--tb=long -s` to see the full response payload in the test output: `docker compose run --rm isolation-tests pytest tests/isolation/test_concurrent_query_isolation.py -v --tb=long -s`

---

## 5 — Common infrastructure failures

### Suite fails immediately with "Service not healthy"

```
FAILED (setup): conftest.py::session_setup
    RuntimeError: postgres service not reachable after 60s: postgresql://postgres@postgres:5432/openkb
```

**Fix**: Start or restart the Compose stack: `docker compose up -d`  
**Check**: `docker compose ps` — all services should show `healthy`

### Azurite blobs missing after seed

```
FAILED tests/isolation/test_concurrent_query_isolation.py::test_concurrent_queries_return_own_citations_only
    azure.core.exceptions.ResourceNotFoundError: The specified blob does not exist.
    BlobPath: kb-aaaaaaaa-.../wiki/summary.md
```

**Fix**: The session fixture's Azurite seed step failed silently. Check `conftest.py` teardown for a prior failed run that left the container in a bad state.  
**Reset**: `docker compose restart azurite && docker compose run --rm isolation-tests`

### Redis connection refused

```
FAILED (setup): conftest.py::session_setup
    ConnectionError: Error connecting to Redis at redis://redis:6379/0
```

**Fix**: `docker compose restart redis`

### Sidecar image not found

```
compiler-worker  | Error: Cannot find sidecar image 'openkb-sidecar:latest'
```

**Fix**: Pull or build the sidecar image before running: `docker pull ghcr.io/vectifyai/openkb:001-fastapi-http-api` (or build from source). Update the `SIDECAR_IMAGE` env var in `docker-compose.yml` if the image tag differs.

---

## 6 — How to reset and re-run

The suite is designed to be fully re-runnable without manual cleanup (SC-005). The `conftest.py` session teardown deletes all KB-A and KB-B Postgres rows and Azurite blobs on exit — even if tests fail.

If the suite was interrupted mid-run (e.g., Ctrl+C), manual cleanup may be required:

```bash
# Check for residual Postgres rows
docker compose exec postgres psql -U postgres -d openkb \
  -c "SELECT id, slug FROM knowledge_bases WHERE slug IN ('kb-a', 'kb-b');"

# If rows exist, delete them (cascades to documents and wiki_pages via FK):
docker compose exec postgres psql -U postgres -d openkb \
  -c "DELETE FROM knowledge_bases WHERE slug IN ('kb-a', 'kb-b');"

# Check for residual Azurite blobs
# (azure-storage-blob SDK or Azurite web UI at http://localhost:10000)

# Check for residual scratch directories (if using volume mount)
docker run --rm -v compiler_scratch:/scratch alpine \
  sh -c "ls /scratch/ 2>/dev/null || echo 'scratch volume empty'"
# If not empty: docker volume rm compiler_scratch && docker compose restart compiler-worker
```

After cleanup:
```bash
docker compose run --rm isolation-tests
```

---

## 7 — Sign-off criteria

Phase 0 isolation is proven when **all of the following conditions hold**:

| Criterion | How to verify |
|-----------|--------------|
| All 12 test functions show `PASSED` | Exit code `0` from `docker compose run --rm isolation-tests` |
| Suite completed within 10 minutes | Check the `s` duration in the pytest summary line |
| No test collected 0 assertions | All test files in `tests/isolation/` were discovered and run |
| Suite was run on a clean machine (no prior state) | Run `docker compose down -v` first, then `docker compose up -d`, then the suite |
| Reviewer confirmed assertion strength | Reviewer has read this runbook and the contracts in `specs/006-sidecar-isolation-validation/contracts/` and agrees the assertions are not trivially weak |

**The sign-off statement** that a reviewer MUST record:

> "I have run `docker compose run --rm isolation-tests` on a clean Compose stack, observed exit code 0 and 12/12 tests passing, and confirm that each test assertion is sufficient to prove the named isolation property. Phase 0 isolation exit criterion is met."

Record the sign-off in the PR description or the spec's checklist (`specs/006-sidecar-isolation-validation/checklists/requirements.md`).

---

## 8 — Escalation

If the suite fails after following the diagnosis steps above:

1. **Check the compiler-worker implementation** (spec 002): does it implement FR-003 (unique scratch dir), FR-004 (dynamic port), FR-012 (teardown regardless of outcome), FR-013 (stateless between jobs)?
2. **Check the generator-api implementation** (spec 003): does it implement FR-004 (per-request scratch directory), FR-005 (dedicated sidecar per request), FR-006 (sidecar lifecycle scoped to request)?
3. **Open an issue** referencing the failing test, the observed vs. expected values, and the compiler-worker or generator-api FR number the failure implicates.
4. **Do not mark Phase 0 as complete** until the suite exits with code `0`. The isolation model is the safety foundation for the multi-tenant layer (Phase 1) — a violation here propagates to every subsequent phase.

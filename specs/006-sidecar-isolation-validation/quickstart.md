# Quickstart: Running the Sidecar Isolation Validation Suite

**Feature**: 006-sidecar-isolation-validation  
**Date**: 2026-06-21

---

## What this suite does

Proves that two concurrent knowledge bases served by the same compiler-worker and generator-api stack never cross-contaminate each other. Five isolation properties are tested:

| # | Scenario | What it proves |
|---|----------|---------------|
| 1 | Scratch directory isolation | Two concurrent jobs get unique, non-overlapping working directories |
| 2 | Port isolation | Two concurrent sidecars bind to different ports; HTTP traffic goes to the right sidecar |
| 3 | Process state isolation | KB-B's sidecar starts clean after KB-A's sidecar is torn down |
| 4 | Sequential reuse safety | After KB-A completes, KB-B starts on a clean slate — no residue from KB-A's port or scratch dir |
| 5 | Concurrent query isolation | Two simultaneous queries each return only their own KB's citations |

A `0` exit code from the suite means **Phase 0 isolation is proven**. Any other exit code means a violation was detected.

---

## Prerequisites

- Docker and Docker Compose installed
- The upstream sidecar image built or pulled (check with `docker images | grep openkb`)
- Repository cloned to a local machine with at least 4 GB free disk space

---

## 1 — Start the full stack

```bash
docker compose up -d postgres azurite redis compiler-worker generator-api
```

Wait for all services to be healthy:

```bash
docker compose ps
```

All five services should show `healthy` or `running`. If any shows `starting`, wait 30 seconds and re-check.

---

## 2 — Run the full isolation suite

```bash
docker compose run --rm isolation-tests
```

This single command:
1. Starts the `isolation-tests` container (from the `test` profile)
2. Seeds Postgres with KB-A and KB-B fixtures
3. Seeds Azurite with pre-compiled wiki blobs for both KBs
4. Runs all five isolation scenarios sequentially
5. Reports pass/fail for each scenario with evidence on failure
6. Tears down fixtures and exits with code `0` (all pass) or `1` (failure)

Expected runtime: **under 10 minutes** on a standard developer machine.

---

## 3 — Run a single scenario (targeted)

```bash
# Scratch directory isolation only:
docker compose run --rm isolation-tests pytest tests/isolation/test_scratch_directory_isolation.py -v

# Port isolation only:
docker compose run --rm isolation-tests pytest tests/isolation/test_port_isolation.py -v

# Process state isolation only:
docker compose run --rm isolation-tests pytest tests/isolation/test_process_state_isolation.py -v

# Sequential reuse safety only:
docker compose run --rm isolation-tests pytest tests/isolation/test_sequential_reuse_safety.py -v

# Concurrent query isolation only:
docker compose run --rm isolation-tests pytest tests/isolation/test_concurrent_query_isolation.py -v
```

---

## 4 — Run without Docker (local pytest, for iteration)

Requires: Docker Compose stack already running, Python env with isolation-tests extras.

```bash
# Install test dependencies
uv sync --extra isolation-tests
# or: pip install -e ".[isolation-tests]"

# Set environment variables (pointing to localhost-published ports)
export POSTGRES_URL="postgresql://postgres:postgres@localhost:5432/openkb"
export AZURITE_BLOB_ENDPOINT="http://localhost:10000/devstoreaccount1"
export REDIS_URL="redis://localhost:6379/0"
export GENERATOR_API_BASE_URL="http://localhost:8001"
export COMPILER_WORKER_SCRATCH_ROOT="/tmp/openkb-scratch"

# Run all scenarios
pytest tests/isolation/ -v --tb=short

# Run with verbose failure output
pytest tests/isolation/ -v --tb=long -s
```

---

## 5 — Interpreting results

### All pass ✅

```
============================================================ 12 passed in 487.3s ===
```

This satisfies the Phase 0 exit criterion: sidecar isolation holds across all five properties.

### Partial failure ❌

```
FAILED tests/isolation/test_port_isolation.py::test_http_to_kba_port_returns_kba_content
  AssertionError: KB-B topic keyword 'chloroplast' found in response from KB-A's sidecar port
  KB-A port: 54321, KB-B port: 54321  ← same port assigned to both sidecars
```

Each failure message includes:
- Which assertion failed
- The observed value (what was found)
- The expected value (what was required)
- The two KB IDs involved

See `RUNBOOK.md` for diagnosis and remediation steps.

---

## Key files

| File | Purpose |
|------|---------|
| `tests/isolation/conftest.py` | Session setup/teardown: Postgres seed, Azurite seed, Compose readiness |
| `tests/isolation/fixtures/kb_a/astronomy-intro.md` | KB-A source document (astronomy) |
| `tests/isolation/fixtures/kb_b/botany-intro.md` | KB-B source document (botany) |
| `tests/isolation/helpers/process_helpers.py` | `wait_for_http()`, `assert_port_bound()`, `assert_proc_dead()` |
| `tests/isolation/helpers/blob_helpers.py` | `seed_wiki_blobs()`, `list_kb_blobs()` |
| `tests/isolation/Dockerfile` | Test container image definition |
| `specs/006-sidecar-isolation-validation/RUNBOOK.md` | Full operational runbook |
| `specs/006-sidecar-isolation-validation/contracts/test-invocation.md` | Env vars, exit codes, Compose definition |
| `specs/006-sidecar-isolation-validation/contracts/kb-fixture-schema.md` | KB-A and KB-B fixture data |

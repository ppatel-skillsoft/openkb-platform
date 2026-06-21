# Contract: Isolation Test Suite Invocation

**Owner**: spec 006-sidecar-isolation-validation  
**Consumers**: CI pipeline, developer runbook, `speckit.tasks`  
**Date**: 2026-06-21

---

## Overview

This document defines the external interface of the isolation test harness: how to invoke it, what environment variables it requires, what exit codes it produces, and how results are reported. It is the machine-readable companion to `RUNBOOK.md`.

---

## Invocation methods

### Method 1: Docker Compose (canonical, CI-ready)

```bash
docker compose run --rm isolation-tests
```

**Prerequisites**:
- Docker Compose stack is running: `docker compose up -d postgres azurite redis compiler-worker generator-api`
- All five services have passed their health checks (Compose `depends_on` with `condition: service_healthy` enforces this automatically)
- The upstream sidecar image is available locally (pulled or built prior to `docker compose up`)

**Behaviour**: The `isolation-tests` service runs pytest against `tests/isolation/` with `-v --tb=short`. On completion the container exits with the pytest exit code.

### Method 2: Direct pytest (local development)

```bash
pytest tests/isolation/ -v --tb=short
```

**Prerequisites**:
- The Docker Compose stack is running (services accessible on localhost at their published ports)
- Python environment has all required packages installed (see §Dependencies below)
- All required environment variables are exported (see §Environment Variables below)

**Behaviour**: Identical to Method 1. The `conftest.py` session fixture detects the absence of `ISOLATION_ENV=docker` and falls back to localhost connection defaults. If required environment variables are missing, the session fixture raises `pytest.UsageError` with a clear message listing missing variables before any test runs.

### Method 3: Single scenario (targeted debugging)

```bash
# Docker Compose:
docker compose run --rm isolation-tests pytest tests/isolation/test_port_isolation.py -v

# Direct pytest:
pytest tests/isolation/test_port_isolation.py -v --tb=long
```

**Behaviour**: Runs only the specified scenario. Session fixtures (Postgres seed, Azurite seed, Compose readiness) still execute. Use this when diagnosing a specific failure without running the full 10-minute suite.

---

## Environment variables

All variables must be set in the `isolation-tests` Compose service definition or exported in the developer's shell for direct pytest invocation. Defaults shown are the Docker Compose internal network addresses.

| Variable | Required | Default (Docker Compose) | Default (localhost fallback) | Description |
|----------|----------|--------------------------|------------------------------|-------------|
| `POSTGRES_URL` | Yes | `postgresql://postgres:postgres@postgres:5432/openkb` | `postgresql://postgres:postgres@localhost:5432/openkb` | asyncpg connection URL for seeding |
| `AZURITE_BLOB_ENDPOINT` | Yes | `http://azurite:10000/devstoreaccount1` | `http://localhost:10000/devstoreaccount1` | Azurite blob service endpoint |
| `REDIS_URL` | Yes | `redis://redis:6379/0` | `redis://localhost:6379/0` | Redis URL for job queue operations |
| `GENERATOR_API_BASE_URL` | Yes | `http://generator-api:8001` | `http://localhost:8001` | generator-api base URL for Scenario 5 |
| `COMPILER_WORKER_SCRATCH_ROOT` | Yes | `/scratch` | `/tmp/openkb-scratch` | Absolute path to the shared scratch volume mount (read-only inside test container) |
| `SIDECAR_TEARDOWN_TIMEOUT_SECONDS` | No | `10` | `10` | Max seconds to wait for a sidecar to fully terminate before asserting it is dead |
| `ISOLATION_ENV` | No | `docker` (set by Compose) | _(not set)_ | Signals to conftest.py whether it is running inside Docker |

### Azurite connection string (for azure-storage-blob SDK)

```
DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVW3zFQ==;BlobEndpoint=${AZURITE_BLOB_ENDPOINT};
```

The account key above is the standard Azurite well-known development key. It is not a secret and is safe to commit.

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All five scenarios passed — isolation is proven |
| `1` | One or more scenarios failed — isolation violation detected or assertion error |
| `2` | Collection error — misconfiguration, missing env var, or test syntax error |
| `3` | Internal pytest error |
| `4` | pytest usage error (e.g., unknown option) |
| `5` | No tests collected (wrong path or marker filter with no matches) |

Exit code `0` is the only code that constitutes Phase 0 sign-off.

---

## Output format

The harness runs with `pytest -v --tb=short` by default:

```
tests/isolation/test_scratch_directory_isolation.py::test_concurrent_scratch_dirs_are_unique PASSED
tests/isolation/test_scratch_directory_isolation.py::test_scratch_dir_cleaned_after_job PASSED
tests/isolation/test_port_isolation.py::test_concurrent_sidecars_bind_different_ports PASSED
tests/isolation/test_port_isolation.py::test_http_to_kba_port_returns_kba_content PASSED
tests/isolation/test_port_isolation.py::test_no_prior_sidecar_on_port_before_new_bind PASSED
...
```

On failure, `--tb=short` produces a concise traceback including the assertion expression and observed vs. expected values. For detailed debugging, use `--tb=long` or `-s` (no output capture).

**JUnit XML** (for CI): add `--junitxml=results/isolation-results.xml` to the `CMD` in the Compose service or pytest invocation. The results file is emitted to a volume-mounted output directory.

---

## Dependencies

Python packages required in the test environment (pinned versions match the project's supply-chain caution policy):

```
pytest==9.0.3
pytest-asyncio==1.3.0
asyncpg==0.29.0
httpx==0.27.0
azure-storage-blob==12.19.1
psutil==5.9.8
```

These are added to `pyproject.toml` under `[project.optional-dependencies]` as `isolation-tests`:

```toml
[project.optional-dependencies]
isolation-tests = [
    "pytest==9.0.3",
    "pytest-asyncio==1.3.0",
    "asyncpg==0.29.0",
    "httpx==0.27.0",
    "azure-storage-blob==12.19.1",
    "psutil==5.9.8",
]
```

Install with: `pip install -e ".[isolation-tests]"` or `uv sync --extra isolation-tests`

---

## Docker Compose service definition

```yaml
# Addition to docker-compose.yml

services:
  isolation-tests:
    build:
      context: .
      dockerfile: tests/isolation/Dockerfile
    profiles: ["test"]
    depends_on:
      postgres:
        condition: service_healthy
      azurite:
        condition: service_healthy
      redis:
        condition: service_healthy
      compiler-worker:
        condition: service_started
      generator-api:
        condition: service_healthy
    environment:
      POSTGRES_URL: postgresql://postgres:postgres@postgres:5432/openkb
      AZURITE_BLOB_ENDPOINT: http://azurite:10000/devstoreaccount1
      REDIS_URL: redis://redis:6379/0
      GENERATOR_API_BASE_URL: http://generator-api:8001
      COMPILER_WORKER_SCRATCH_ROOT: /scratch
      ISOLATION_ENV: docker
    volumes:
      - compiler_scratch:/scratch:ro    # read-only; worker writes, tests read
    command: ["pytest", "tests/isolation/", "-v", "--tb=short"]

volumes:
  compiler_scratch:    # shared named volume between compiler-worker and isolation-tests
```

**Note**: The `profiles: ["test"]` declaration ensures the `isolation-tests` service is excluded from `docker compose up` (normal developer workflow). It is only instantiated when explicitly referenced with `docker compose run --rm isolation-tests` or `docker compose --profile test up`.

---

## Scratch volume addition to compiler-worker

The `compiler-worker` service gains a single volume mount. This is the only change to existing Compose service definitions:

```yaml
  compiler-worker:
    # ... existing definition ...
    volumes:
      - compiler_scratch:/scratch    # SCRATCH_DIR_ROOT must be set to /scratch
    environment:
      # ... existing env vars ...
      SCRATCH_DIR_ROOT: /scratch
```

No compiler-worker code changes are required. The `SCRATCH_DIR_ROOT` env var is expected to already be configurable (spec 002 FR-003: "unique, isolated temporary scratch directory").

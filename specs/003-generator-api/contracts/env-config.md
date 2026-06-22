# Contract: Generator API Environment Configuration

**Branch**: `004-generator-api` | **Date**: 2026-06-21
**Service**: `generator_api`
**Pattern**: Inherits shared pattern from [`specs/002-compiler-worker-skeleton/contracts/env-config.md`](../../002-compiler-worker-skeleton/contracts/env-config.md)

---

## Settings Class

```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # ── Database ────────────────────────────────────────────────────────────
    database_url: str                          # Required: postgresql+asyncpg://...

    # ── Blob Storage ────────────────────────────────────────────────────────
    azure_storage_connection_string: str       # Required: Azurite or Azure conn string
    azure_kb_container: str = "openkb"        # Container name

    # ── LLM (forwarded to sidecar subprocess) ───────────────────────────────
    llm_api_key: str = ""                      # Required at query time; empty = LLM fail

    # ── Sidecar ─────────────────────────────────────────────────────────────
    sidecar_startup_timeout: int = 30          # Seconds to wait for sidecar readiness
    generator_request_timeout: int = 300       # Seconds before HTTP 504 to caller

    # ── Scratch Storage ─────────────────────────────────────────────────────
    scratch_dir_root: Path = Path("/tmp/generator-scratch")

    # ── Server ──────────────────────────────────────────────────────────────
    generator_host: str = "0.0.0.0"           # Use 127.0.0.1 for standalone debug
    generator_port: int = 8001

    model_config = {"env_file": ".env", "extra": "ignore"}
```

---

## All Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | Async PostgreSQL DSN |
| `AZURE_STORAGE_CONNECTION_STRING` | ✅ | — | Azurite or Azure Blob connection string |
| `AZURE_KB_CONTAINER` | No | `openkb` | Blob container for wiki trees |
| `LLM_API_KEY` | ✅ at query time | `""` | Forwarded to sidecar subprocess |
| `SIDECAR_STARTUP_TIMEOUT` | No | `30` | Sidecar readiness poll timeout (seconds) |
| `GENERATOR_REQUEST_TIMEOUT` | No | `300` | End-to-end query timeout → HTTP 504 (seconds) |
| `SCRATCH_DIR_ROOT` | No | `/tmp/generator-scratch` | Root for per-request scratch dirs |
| `GENERATOR_HOST` | No | `0.0.0.0` | Bind host for uvicorn |
| `GENERATOR_PORT` | No | `8001` | Bind port |

---

## Startup Validation

The FastAPI lifespan handler checks all required variables and dependencies at startup:

1. `DATABASE_URL` set and Postgres reachable (`SELECT 1`) → else `RuntimeError`
2. `AZURE_STORAGE_CONNECTION_STRING` set and Azurite reachable (list containers) → else `RuntimeError`
3. `LLM_API_KEY` set (non-empty) → log WARNING if missing; service starts but queries will fail at
   sidecar level (LLM will reject the request)

The service does **not** fail to start on missing `LLM_API_KEY` — this allows health checks and
pre-flight validation to work even before LLM credentials are configured.

---

## Port Convention (Phase 0)

| Service | Default Port | Notes |
|---------|-------------|-------|
| sidecar (compiler-worker jobs) | dynamic (random) | Localhost only |
| sidecar (generator-api queries) | dynamic (random) | Localhost only |
| compiler-worker | — | Worker process, no inbound port |
| generator-api | `8001` | Exposed on host via Docker Compose |
| azurite | `10000` | Exposed on host |
| postgres | `5432` | Exposed on host |
| redis | `6379` | Exposed on host |

---

## Docker Compose Fragment

```yaml
generator-api:
  build:
    context: .
    dockerfile: Dockerfile.generator-api
  container_name: openkb-generator-api
  ports:
    - "8001:8001"
  env_file:
    - .env
  environment:
    DATABASE_URL: "postgresql+asyncpg://openkb:openkb@postgres:5432/openkb"
    AZURE_STORAGE_CONNECTION_STRING: "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1"
    AZURE_KB_CONTAINER: openkb
  depends_on:
    postgres:
      condition: service_healthy
    azurite:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-sf", "http://localhost:8001/health"]
    interval: 10s
    timeout: 5s
    retries: 6
    start_period: 20s
  restart: unless-stopped
```

---

## Standalone Debug (no Docker)

```bash
export DATABASE_URL="postgresql+asyncpg://openkb:openkb@localhost:5432/openkb"
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1"
export LLM_API_KEY="your-key"
export GENERATOR_HOST="127.0.0.1"

python -m generator_api
# Starts on http://127.0.0.1:8001
```

Requires Postgres and Azurite to be reachable at localhost (can be running via Docker Compose
with only those two services started).

# Contract: Environment Variable Configuration

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Module**: `compiler_worker/config.py` (`WorkerConfig` dataclass)

---

## Overview

All worker configuration is read from environment variables at startup.
Missing required variables cause an immediate `ValueError` (fail-fast).
Optional variables fall back to documented defaults.

---

## Variables

### Postgres

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `DATABASE_URL` | ✅ | — | `postgresql+asyncpg://openkb:openkb@localhost:5432/openkb` | SQLAlchemy async connection URL. Use `postgresql+asyncpg://` scheme. Production: Azure Database for PostgreSQL Flexible Server endpoint. |

---

### Redis Queue

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `REDIS_URL` | ✅ | — | `redis://localhost:6379/0` | Redis connection URL. |
| `QUEUE_KEY` | ✗ | `compiler:jobs` | `compiler:jobs` | Redis list key to consume from. |
| `QUEUE_POLL_TIMEOUT_S` | ✗ | `5` | `5` | BRPOP timeout in seconds. Controls how quickly the worker responds to SIGTERM. |

---

### Blob Storage

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | ✅ | — | `DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;...` | Azure Blob Storage connection string. For Azurite local dev use the well-known devstoreaccount1 connection string. |

---

### Sidecar

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `SIDECAR_CMD` | ✅ | — | `uvicorn openkb.api.app:app` | Command (and args) used to start the sidecar process. Passed to `subprocess.Popen` as a shell string. The worker appends `--host 127.0.0.1 --port {port}` automatically. |
| `SIDECAR_STARTUP_TIMEOUT_S` | ✗ | `15` | `15` | Seconds to wait for sidecar to respond to `GET /health` after spawn. |
| `SIDECAR_COMPILE_TIMEOUT_S` | ✗ | `300` | `300` | Seconds before the worker gives up polling `/status` and declares a timeout failure. |
| `SIDECAR_POLL_INTERVAL_S` | ✗ | `2.0` | `2.0` | Seconds between each `GET /status` poll. |

---

### Phase 0 KB Scope

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `KB_ID` | ✅ | — | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | UUID of the single hardcoded knowledge base used in Phase 0. The worker uses this to scope stale-document recovery on startup. |

---

### Logging

| Variable | Required | Default | Example | Description |
|---|---|---|---|---|
| `LOG_LEVEL` | ✗ | `INFO` | `DEBUG` | Python `logging` level name. The worker logs to stdout only. |

---

## Docker Compose Defaults

The `docker-compose.yml` sets the following defaults for local development:

```yaml
environment:
  DATABASE_URL: "postgresql+asyncpg://openkb:openkb@postgres:5432/openkb"
  REDIS_URL: "redis://redis:6379/0"
  AZURE_STORAGE_CONNECTION_STRING: >-
    DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;
    AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFor392Sdeds...;
    BlobEndpoint=http://azurite:10000/devstoreaccount1;
  SIDECAR_CMD: "uvicorn openkb.api.app:app"
  KB_ID: "00000000-0000-0000-0000-000000000001"
  LOG_LEVEL: "INFO"
```

---

## Standalone Debug (`.env` file)

For running `python -m compiler_worker` outside Docker:

```dotenv
DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb
REDIS_URL=redis://localhost:6379/0
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFor392Sdeds...;BlobEndpoint=http://localhost:10000/devstoreaccount1;
SIDECAR_CMD=uvicorn openkb.api.app:app
KB_ID=00000000-0000-0000-0000-000000000001
LOG_LEVEL=DEBUG
```

The worker calls `load_dotenv()` on startup so a `.env` file in the working
directory is automatically picked up (same pattern as `openkb` CLI).

---

## Fail-Fast Validation

```python
# compiler_worker/config.py
import os
from dataclasses import dataclass, field

REQUIRED = [
    "DATABASE_URL",
    "REDIS_URL",
    "AZURE_STORAGE_CONNECTION_STRING",
    "SIDECAR_CMD",
    "KB_ID",
]

@dataclass
class WorkerConfig:
    database_url: str
    redis_url: str
    blob_connection_string: str
    sidecar_cmd: str
    kb_id: str
    queue_key: str = "compiler:jobs"
    queue_poll_timeout: int = 5
    sidecar_startup_timeout: int = 15
    sidecar_compile_timeout: int = 300
    sidecar_poll_interval: float = 2.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        missing = [k for k in REQUIRED if not os.environ.get(k)]
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")
        return cls(
            database_url=os.environ["DATABASE_URL"],
            redis_url=os.environ["REDIS_URL"],
            blob_connection_string=os.environ["AZURE_STORAGE_CONNECTION_STRING"],
            sidecar_cmd=os.environ["SIDECAR_CMD"],
            kb_id=os.environ["KB_ID"],
            queue_key=os.environ.get("QUEUE_KEY", "compiler:jobs"),
            queue_poll_timeout=int(os.environ.get("QUEUE_POLL_TIMEOUT_S", "5")),
            sidecar_startup_timeout=int(os.environ.get("SIDECAR_STARTUP_TIMEOUT_S", "15")),
            sidecar_compile_timeout=int(os.environ.get("SIDECAR_COMPILE_TIMEOUT_S", "300")),
            sidecar_poll_interval=float(os.environ.get("SIDECAR_POLL_INTERVAL_S", "2.0")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
```

# Quickstart: Persistent KB Sidecar Pool

**Feature**: 010-persistent-kb-sidecar-pool
**Phase**: 1 — Design
**Audience**: Developer contributing to or testing this feature locally

---

## Prerequisites

- Docker and Docker Compose installed
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Repository cloned and on branch `010-persistent-kb-sidecar-pool`
- An `openkb-core` executable available (either from the pinned tag in `pyproject.toml` or
  `openkb serve` on your `PATH` inside the container)

---

## 1. Configure environment

Copy the example config and set required values:

```bash
cp config.yaml.example config.yaml
cp .env.example .env   # if present, or create manually
```

Minimum `.env` content for local development (using Azurite as the blob emulator):

```env
# Database
DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb

# Blob Storage (Azurite emulator — already in docker-compose.yml)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OGIVLJUKjnU+s5h/RiRiGhGNXyNidcHg1Kqt3OomBs=;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;

# LLM (required for real queries; can be a dummy key for pool/invalidate-only tests)
LLM_API_KEY=sk-...

# New in this feature — tune for local testing
GENERATOR_SIDECAR_IDLE_TTL_SECONDS=60   # 1 minute idle TTL for fast local eviction tests
GENERATOR_REQUEST_TIMEOUT=120
GENERATOR_SIDECAR_STARTUP_TIMEOUT=30

# Optional — uncomment to pre-warm sidecars on startup
# GENERATOR_PREWARM_ON_STARTUP=true

# compiler_worker → generator_api notification URL
GENERATOR_API_URL=http://generator-api:8001
```

---

## 2. Start the full stack

```bash
docker compose up --build
```

This starts:
- `postgres` — Postgres 16 (port 5432)
- `azurite` — Azure Blob Storage emulator (port 10000)
- `generator-api` — FastAPI service (port 8001)
- `compiler-worker` — Async Postgres queue consumer

Wait until you see:

```
generator-api  | INFO  generator_api.app — Generator API v... starting — all dependencies reachable
compiler-worker | INFO  compiler_worker.worker — Worker started — queue_backend=postgres
```

---

## 3. Verify the pool is running

Health check (should return 200):

```bash
curl -s http://localhost:8001/health | jq .
# Expected: {"status": "ok", "postgres": "ok", "azurite": "ok"}
```

---

## 4. Issue a query (cold start)

On the first query to a KB, the pool will sync blobs and start a sidecar. This takes 5–30 s.

```bash
KB_ID="<uuid-of-a-ready-kb>"

curl -s -X POST "http://localhost:8001/kbs/${KB_ID}/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarise the key topics in this knowledge base."}' | jq .
```

Watch the `generator-api` logs to see the cold start:

```
INFO  generator_api.pool — Starting sidecar for kb_id=<uuid> (kb_slug=my-kb)
INFO  generator_api.sidecar — Starting sidecar on port 54321 (kb_slug=my-kb)
INFO  generator_api.sidecar — Sidecar healthy on port 54321 after 4.5s
INFO  generator_api.pool — Sidecar for kb_id=<uuid> is ready
```

---

## 5. Verify warm query (< 2 s)

Issue a second query immediately:

```bash
time curl -s -X POST "http://localhost:8001/kbs/${KB_ID}/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What documents are in this knowledge base?"}' | jq .answer
```

The response should arrive in under 2 seconds. The `generator-api` logs should show:

```
INFO  generator_api.pool — Routing query to existing sidecar for kb_id=<uuid>
```

No blob sync or process start is logged.

---

## 6. Trigger invalidation manually

```bash
curl -s -X POST "http://localhost:8001/kbs/${KB_ID}/invalidate" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "test-manual-invalidation"}' \
  -w "\nHTTP %{http_code}\n"
# Expected: HTTP 204
```

Logs should show:

```
INFO  generator_api.pool — KB <uuid> marked stale (document_id=test-manual-invalidation)
```

The next query to the KB will trigger a fresh cold start.

---

## 7. Test idle eviction (short TTL)

Set `GENERATOR_SIDECAR_IDLE_TTL_SECONDS=5` in your `.env` and restart `generator-api`.

Wait 70 s (TTL + one eviction check interval of 60 s), then check the logs:

```
INFO  generator_api.pool — Evicting idle sidecar for kb_id=<uuid> (idle=65s > ttl=5s)
INFO  generator_api.sidecar — Sending SIGTERM to sidecar PID ...
```

Issue a new query — you should see a cold start again.

---

## 8. Run tests

```bash
# Full test suite (from repo root)
uv run pytest

# Unit tests only (fast, no Docker required)
uv run pytest tests/unit/

# generator_api unit tests specifically
uv run pytest tests/unit/generator_api/ -v

# Integration tests (requires running stack — docker compose up first)
uv run pytest tests/integration/generator_api/ -v

# Isolation tests
uv run pytest tests/isolation/ -v

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run bandit -r .
```

---

## 9. Verify clean shutdown

```bash
# With at least one warm sidecar running:
docker compose stop generator-api

# Check no orphaned openkb serve processes remain:
ps aux | grep "openkb serve" | grep -v grep
# Expected: no output
```

The `generator-api` shutdown logs should show:

```
INFO  generator_api.app — Generator API shutting down
INFO  generator_api.pool — Shutting down SidecarPool (N active sidecars)
INFO  generator_api.pool — Sidecar for kb_id=<uuid> stopped (reason: shutdown)
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `502 Sidecar failed to start` | `openkb serve` not on PATH inside container | Verify `openkb-core` is installed in the Docker image |
| Warm query still takes 5+ s | Pool entry is stale or was evicted | Check logs for stale/eviction messages; first query after invalidation is always cold |
| `POST /invalidate` returns 404 | KB UUID does not exist in `knowledge_bases` table | Verify the KB was created via the normal onboarding flow |
| Sidecar crashes mid-query | `openkb serve` process instability | Check `generator-api` logs for `WARNING SidecarCrashedError`; pool will restart on next query |
| `asyncio.TimeoutError` on query | LLM is slow or unresponsive | Increase `GENERATOR_REQUEST_TIMEOUT`; check LLM API connectivity |

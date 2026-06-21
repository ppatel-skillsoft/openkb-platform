# Quickstart: Compiler Worker (Phase 0)

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Branch**: `003-compiler-worker-skeleton`

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin) installed and running
- Git
- Python 3.10+ with `uv` (for standalone debug mode only)

---

## Option A — Docker Compose (recommended)

### 1. Clone and switch to the feature branch

```bash
git clone https://github.com/ppatel-skillsoft/OpenKB.git
cd OpenKB
git checkout 003-compiler-worker-skeleton
```

### 2. Start the full stack

```bash
docker compose up --build
```

This starts five services:

| Service | Image | Purpose |
|---|---|---|
| `postgres` | `postgres:15-alpine` | Postgres database (applies migrations on first start) |
| `azurite` | `mcr.microsoft.com/azure-storage/azurite` | Local Azure Blob Storage emulator |
| `redis` | `redis:7-alpine` | Job queue |
| `sidecar` | Built from this repo (`001-fastapi-http-api` branch) | OpenKB FastAPI sidecar (one per job, managed by the worker) |
| `compiler-worker` | Built from `Dockerfile.compiler-worker` | The compiler worker service |

Wait for all services to reach a healthy state. The worker logs:
```
INFO  compiler_worker.worker: Startup recovery complete (0 stale documents resolved)
INFO  compiler_worker.worker: Worker started — polling compiler:jobs
```

### 3. Upload a test document to Azurite

```bash
# Install Azure CLI or use the Azurite REST API directly
# The Azurite blob endpoint is exposed at localhost:10000

# Using azure-cli:
az storage container create \
  --name "kb-00000000-0000-0000-0000-000000000001" \
  --connection-string "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFor392Sdeds...;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"

az storage blob upload \
  --container-name "kb-00000000-0000-0000-0000-000000000001" \
  --name "raw/hello.md" \
  --file /path/to/hello.md \
  --connection-string "DefaultEndpointsProtocol=http;..."
```

### 4. Seed the Postgres database

```bash
# Ensure a knowledge_bases and documents row exist for KB_ID
docker compose exec postgres psql -U openkb openkb -c "
INSERT INTO knowledge_bases (id, name, slug, storage_container_path, compilation_config, status)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Phase 0 Test KB',
  'phase0-test',
  'kb-00000000-0000-0000-0000-000000000001',
  '{\"model\": \"gpt-5.4-mini\", \"language\": \"en\"}'::jsonb,
  'active'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO documents (id, kb_id, source_type, source_uri, original_filename, status)
VALUES (
  gen_random_uuid(),
  '00000000-0000-0000-0000-000000000001',
  'markdown',
  'kb-00000000-0000-0000-0000-000000000001/raw/hello.md',
  'hello.md',
  'pending'
) RETURNING id;
"
# Note the returned document id — you'll need it for the queue message
```

### 5. Enqueue a compilation job

```bash
docker compose exec redis redis-cli LPUSH compiler:jobs \
  "{\"job_id\":\"$(uuidgen)\",\"kb_id\":\"00000000-0000-0000-0000-000000000001\",\"document_id\":\"<DOCUMENT_ID_FROM_STEP_4>\",\"blob_path\":\"kb-00000000-0000-0000-0000-000000000001/raw/hello.md\",\"filename\":\"hello.md\",\"enqueued_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
```

### 6. Observe compilation

```bash
docker compose logs -f compiler-worker
```

Expected output:
```
INFO  compiler_worker.worker: Dequeued job <job_id> (document: <doc_id>)
INFO  compiler_worker.job:    Downloading blob kb-.../raw/hello.md
INFO  compiler_worker.job:    Transitioning document <doc_id> → compiling
INFO  compiler_worker.sidecar: Sidecar started on port 54321 (PID 12345)
INFO  compiler_worker.sidecar: POST /init → 200
INFO  compiler_worker.sidecar: POST /add → 202
INFO  compiler_worker.sidecar: Polling /status... [compiling]
INFO  compiler_worker.sidecar: Polling /status... [complete] (3 pages)
INFO  compiler_worker.job:    Uploading 3 wiki pages to Blob Storage
INFO  compiler_worker.job:    Upserting 3 wiki_pages rows in Postgres
INFO  compiler_worker.job:    Document <doc_id> → complete (tokens: 1234, pageindex: false)
INFO  compiler_worker.sidecar: Sidecar torn down (PID 12345 exited)
INFO  compiler_worker.worker: Job <job_id> complete in 42.3s
```

### 7. Verify results

```bash
# Postgres — document should be 'complete'
docker compose exec postgres psql -U openkb openkb -c \
  "SELECT id, status, token_cost, pageindex_used FROM documents WHERE id = '<doc_id>';"

# Postgres — wiki_pages rows
docker compose exec postgres psql -U openkb openkb -c \
  "SELECT slug, page_type, blob_path FROM wiki_pages WHERE kb_id = '00000000-0000-0000-0000-000000000001';"

# Azurite — wiki blobs should be present
az storage blob list \
  --container-name "kb-00000000-0000-0000-0000-000000000001" \
  --prefix "wiki/" \
  --connection-string "DefaultEndpointsProtocol=http;..." \
  --output table
```

---

## Option B — Standalone Debug Mode

Run the worker directly on your machine (without Docker), pointing at local
service ports exposed by Docker Compose.

### 1. Start only the infrastructure services

```bash
docker compose up postgres azurite redis --build
```

### 2. Install worker dependencies

```bash
uv pip install -e ".[dev]"
uv pip install redis azure-storage-blob httpx aiofiles
```

### 3. Set environment variables

```bash
export DATABASE_URL="postgresql+asyncpg://openkb:openkb@localhost:5432/openkb"
export REDIS_URL="redis://localhost:6379/0"
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFor392Sdeds...;BlobEndpoint=http://localhost:10000/devstoreaccount1;"
export SIDECAR_CMD="uvicorn openkb.api.app:app"
export KB_ID="00000000-0000-0000-0000-000000000001"
export LOG_LEVEL="DEBUG"
```

Or create a `.env` file in the project root — the worker calls `load_dotenv()`
automatically.

### 4. Run the worker

```bash
python -m compiler_worker
```

### 5. Follow steps 3–7 from Option A

---

## Resetting the Local Stack

```bash
# Stop and remove all containers + volumes (wipes Postgres data + Azurite blobs)
docker compose down -v

# Re-start from scratch
docker compose up --build
```

---

## Running Tests

```bash
# Unit tests (no external services required)
uv run pytest tests/unit/compiler_worker/ -v

# Integration tests (requires Docker Compose stack running)
docker compose up postgres azurite redis -d
uv run pytest tests/integration/compiler_worker/ -v
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Worker exits immediately with `ValueError: Missing required env vars` | Required env vars not set | Check `.env` file or `docker-compose.yml` environment block |
| `Sidecar failed to start within 15s` | Sidecar image not built or port conflict | Run `docker compose build sidecar`; check `SIDECAR_CMD` |
| `ResourceNotFoundError` on blob download | Container or blob doesn't exist | Ensure container `kb-{id}` exists and blob was uploaded (Step 3) |
| Document stuck in `compiling` after restart | Worker was killed mid-job | Restart the worker — startup recovery sets stale `compiling` docs to `failed` |
| `Connection refused` on `localhost:5432` | Postgres not running | Run `docker compose up postgres` |

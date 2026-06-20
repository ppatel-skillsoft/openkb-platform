# Quickstart: OpenKB HTTP API

**Feature**: `001-fastapi-http-api`
**Date**: 2026-06-19

---

## Local Development with Docker Compose *(recommended)*

This is the primary local development path. No Azure account required — Azurite
(Microsoft's official Azure Blob Storage emulator) runs as a sidecar container and
the `AzureBlobStorageBackend` connects to it identically to how it connects to real Azure.

### 1. Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin) installed
- An LLM API key (OpenAI, Anthropic, etc.)

### 2. Configure environment

```bash
cp .env.docker .env
# Edit .env and set your LLM key:
#   LLM_API_KEY=sk-...
# Everything else is pre-filled for Azurite — no changes needed.
```

`.env.docker` (pre-filled, safe to commit without real secrets):
```dotenv
OPENKB_STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=<AZURITE_DEV_KEY>;BlobEndpoint=http://azurite:10000/devstoreaccount1
AZURE_KB_CONTAINER=openkb
LLM_API_KEY=                        # <-- fill this in
```

### 3. Start the stack

```bash
docker compose up
```

This starts two services:
- **azurite** — Azure Blob Storage emulator on port 10000
- **api** — OpenKB FastAPI server on port 8000

The API is ready within ~10 seconds. You'll see:
```
api-1      | INFO:     Application startup complete.
api-1      | INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 4. Use the API

```bash
# Initialise a KB
curl -X POST http://localhost:8000/kb/init \
  -H "Content-Type: application/json" \
  -d '{"kb_name": "my-kb", "model": "gpt-5.4-mini", "language": "en"}'
# → {"kb_name":"my-kb","status":"created","message":"Knowledge base 'my-kb' initialised."}

# Add a document (URL)
curl -X POST http://localhost:8000/kb/add \
  -H "Content-Type: application/json" \
  -d '{"kb_name": "my-kb", "source": "https://arxiv.org/pdf/2304.01373"}'
# → {"status":"added","doc_name":"attention-is-all-you-need-a1b2c3d4","message":"..."}

# Query
curl -X POST http://localhost:8000/kb/query \
  -H "Content-Type: application/json" \
  -d '{"kb_name": "my-kb", "question": "What is the attention mechanism?"}'
# → {"answer":"The attention mechanism...","saved_to":null}

# List contents
curl "http://localhost:8000/kb/list?kb_name=my-kb"

# Check status
curl "http://localhost:8000/kb/status?kb_name=my-kb"
```

### 5. The CLI still works unchanged

```bash
# CLI uses LocalStorageBackend; Docker stack uses AzureBlobStorageBackend.
# Both are independent — the CLI path is unaffected.
openkb init
openkb add paper.pdf
openkb query "What are the findings?"
```

---

## Running Without Docker (local filesystem backend)

For rapid iteration on the API code itself, skip Docker and use the local backend:

```bash
pip install 'openkb[api,dev]'

export OPENKB_STORAGE_BACKEND=local
export OPENKB_BASE_DIR=/tmp/kbs
export LLM_API_KEY=sk-...

openkb serve --reload    # auto-reloads on code changes
```

---

## Promoting to Real Azure (when ready)

**No code changes.** Replace the connection string in your environment:

```dotenv
# .env (production — keep out of version control)
OPENKB_STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=openkbstore;AccountKey=<real-key>;EndpointSuffix=core.windows.net
AZURE_KB_CONTAINER=openkb
LLM_API_KEY=sk-...
```

See `.env.azure.example` for the full template. Provision Azure resources:

```bash
az group create --name openkb-rg --location eastus
az storage account create --name openkbstore --resource-group openkb-rg \
  --sku Standard_LRS --allow-blob-public-access false
az storage container create --name openkb --account-name openkbstore
az storage account show-connection-string --name openkbstore \
  --resource-group openkb-rg --query connectionString -o tsv
```

---

## Running Tests

```bash
# Unit tests (no LLM, no Docker, no Azure)
pytest tests/unit/ -v

# Integration tests (local backend, mocked compiler)
pytest tests/integration/ -v

# Contract tests (schema assertions only)
pytest tests/contract/ -v

# Full suite
pytest
```

---

## Concurrent Safety

Multiple API replicas can share the same KB safely. Write operations (`/kb/init`,
`/kb/add`) acquire an Azure Blob Lease on an `ingest.lock` blob per KB:

- Concurrent writes: second request waits up to 30 s then returns HTTP 503 if the
  lease isn't released ("KB is busy; retry after a moment")
- Read operations (`/kb/query`, `/kb/list`, `/kb/status`) require no lock

This behaviour is identical against Azurite and real Azure.

---

## Error Reference

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 200 | Success | — |
| 404 | KB not found | Call `POST /kb/init` first |
| 409 | KB already exists | Use existing KB or choose a different `kb_name` |
| 422 | Validation error | Check `detail` field for the specific field and rule |
| 502 | LLM API error | Check `LLM_API_KEY` and LLM provider status |
| 503 | KB busy (lock timeout) | Retry after a moment; another request is writing |

# Quickstart: Phase 0 Generator API Service

**Branch**: `004-generator-api` | **Date**: 2026-06-21

---

## Prerequisites

- Docker and Docker Compose installed
- Repository cloned: `git clone https://github.com/ppatel-skillsoft/OpenKB && cd OpenKB`
- A compiled knowledge base in the local stack (see Seed Data below)

---

## Option A — Full Docker Compose Stack (Recommended)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and set:
#   LLM_API_KEY=<your key>
# Everything else is pre-filled for local Azurite + Postgres.
```

### 2. Start the full stack

```bash
docker compose up
```

This starts: `postgres`, `azurite`, `redis`, `compiler-worker`, and `generator-api`.

The generator-api is healthy when:
```bash
curl -sf http://localhost:8001/health
# → {"status":"ok","postgres":"ok","azurite":"ok"}
```

### 3. Seed the database and compile a document

```bash
# Apply migrations (auto-applied on first start via compose init container)
# Seed: create a KB record and add a document
docker compose exec generator-api python -m generator_api.seed

# Or manually: upload a document and enqueue a compilation job
# (see compiler-worker quickstart for details)
```

### 4. Query the knowledge base

```bash
# Get the KB ID from Postgres
KB_ID=$(docker compose exec postgres psql -U openkb -d openkb -t -c \
  "SELECT id FROM knowledge_bases LIMIT 1;" | tr -d ' ')

# Send a query
curl -s -X POST "http://localhost:8001/kbs/${KB_ID}/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the main topic of this knowledge base?"}' | python -m json.tool
```

Expected response:
```json
{
  "answer": "The knowledge base covers...",
  "citations": [],
  "tokens_used": 0
}
```

---

## Option B — Standalone Python Process (Inner-Loop Debug)

Use this when you want to iterate on `generator_api/` code without rebuilding Docker images.
Requires Postgres and Azurite to be running (can be a subset of the Compose stack).

### 1. Start only the infrastructure services

```bash
docker compose up postgres azurite redis
```

### 2. Install the package with API extras

```bash
# Requires Python 3.10+
pip install -e ".[api]"
# Or with uv:
uv pip install -e ".[api]"
```

### 3. Export environment variables

```bash
export DATABASE_URL="postgresql+asyncpg://openkb:openkb@localhost:5432/openkb"
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1"
export LLM_API_KEY="your-key"
export GENERATOR_HOST="127.0.0.1"
export GENERATOR_PORT="8001"
```

### 4. Start the service

```bash
python -m generator_api
# → INFO:     Uvicorn running on http://127.0.0.1:8001
```

### 5. Health check

```bash
curl http://127.0.0.1:8001/health
```

---

## Running Tests

### Unit tests (no Docker required)

```bash
pytest tests/unit/ -v
```

### Integration tests (Docker Compose stack required)

```bash
docker compose up -d postgres azurite
pytest tests/integration/ -v
```

---

## Seed Data

To create a KB with compiled content for manual testing, use the seed fixture:

```bash
# Via Docker Compose:
docker compose exec generator-api python -m generator_api.seed

# Standalone:
python -m generator_api.seed
```

This creates:
- 1 `knowledge_bases` row with `status='active'`
- 2 `documents` rows with `status='complete'`
- Uploads a sample wiki tree to Azurite under `kb-{id}/wiki/`

---

## Common Issues

### `openkb` not found in PATH inside container

The sidecar binary (`openkb serve`) must be available in the container. The generator-api
`Dockerfile` installs `openkb[api]` which provides the `openkb` CLI entry point.

```dockerfile
RUN pip install "openkb[api]"
```

### Sidecar fails to start: "LLM_API_KEY not set"

Set `LLM_API_KEY` in your `.env` file. The sidecar requires it to make LLM calls.

### Query returns `{"answer": "I cannot find relevant information", "citations": [], "tokens_used": 0}`

The wiki tree may be empty or the question may not match any compiled content. Verify:
```bash
# Check compiled documents
docker compose exec postgres psql -U openkb -d openkb -c \
  "SELECT id, status FROM documents WHERE status='complete';"

# Check wiki blobs in Azurite
az storage blob list \
  --account-name devstoreaccount1 \
  --account-key Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw== \
  --connection-string "DefaultEndpointsProtocol=http;..." \
  --container-name openkb \
  --prefix "kb-{id}/wiki/" \
  --query "[].name" -o tsv
```

### 409 "KB has no compiled documents"

Run the compiler-worker to compile documents first. The generator-api requires at least one
document with `status='complete'` in Postgres before accepting queries.

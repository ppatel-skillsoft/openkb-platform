# openkb-platform

Service layer for running OpenKB at scale — multi-tenant Generator API, async Compiler Worker, and a local-first Docker Compose stack.

## Services

| Service | Description |
|---------|-------------|
| `generator_api` | FastAPI service that accepts query/ingest requests and manages per-KB `openkb serve` sidecars |
| `compiler_worker` | Async worker that polls a Postgres job queue (SKIP LOCKED) and runs `openkb compile` per document |
| `openkb` sidecar | One `openkb serve` process per active KB, spawned on demand by the generator API |

The core `openkb` CLI and Python package lives in [openkb-core](https://github.com/ppatel-skillsoft/openkb-core), installed as a pip dependency from a pinned git tag.

## Requirements

- Docker + Docker Compose
- A `.env` file (copy from `.env.example`)

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

Services start on:
- Generator API: `http://localhost:8001`
- OpenKB sidecar API: `http://localhost:8000`

## Environment Variables

See `.env.example` for all required and optional variables. Key ones:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob storage (Azurite locally) |
| `OPENKB_CORE_VERSION` | Git tag of openkb-core to use (e.g. `v0.1.0`) |

## Running Tests

```bash
# Isolation tests (requires services running)
docker compose --profile test run --rm isolation-tests
```

The isolation test suite validates:
- Per-KB content isolation (no cross-contamination between knowledge bases)
- Concurrent query correctness
- Scratch directory isolation and cleanup
- Process state isolation across sequential queries

## Project Structure

```
compiler_worker/   Postgres queue consumer and document compilation pipeline
generator_api/     FastAPI app, route handlers, sidecar lifecycle management
tests/isolation/   End-to-end isolation test suite
docker-compose.yml Full local stack
specs/             Feature specifications and implementation plans
```

## Related

- [openkb-core](https://github.com/ppatel-skillsoft/openkb-core) — the `openkb` Python package

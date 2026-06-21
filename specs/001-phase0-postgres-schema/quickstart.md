# Quickstart: Phase 0 Postgres Schema

**Branch**: `002-phase0-postgres-schema`
**Date**: 2026-06-21
**Goal**: Get a running local Postgres instance with the Phase 0 schema applied in under 5 minutes from a clean clone (SC-001).

---

## Prerequisites

| Tool | Minimum version | Check |
|------|----------------|-------|
| Docker Desktop (or Docker Engine + Compose v2) | Docker 24+, Compose v2 | `docker compose version` |
| Python | 3.10+ | `python --version` |
| uv | any recent | `uv --version` |

---

## Step 1 — Clone and install

```bash
git clone https://github.com/ppatel-skillsoft/OpenKB.git
cd OpenKB

# Install Python dependencies (including the new db extras)
uv sync --extra dev
```

---

## Step 2 — Configure environment

```bash
cp .env.example .env
# .env is pre-populated with local dev defaults — no edits needed for local use
```

The `.env.example` file ships with:
```dotenv
DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb
POSTGRES_USER=openkb
POSTGRES_PASSWORD=openkb
POSTGRES_DB=openkb
```

> **Production**: Set `DATABASE_URL` in your container runtime environment:
> ```
> postgresql+asyncpg://openkb:<password>@<azure-host>:5432/openkb?ssl=require
> ```
> No code changes required between environments (FR-013).

---

## Step 3 — Start Postgres and apply migrations

```bash
docker compose up --wait
```

This command:
1. Pulls `postgres:15-alpine` if not already cached
2. Starts the `postgres` service and waits for `pg_isready` health check to pass
3. Runs the `migrate` service, which executes `alembic upgrade head`
4. Returns once both services are healthy

Expected output (abridged):
```
✔ Container openkb-postgres-1  Healthy
✔ Container openkb-migrate-1   Exited (0)
```

To verify the schema was applied:
```bash
docker compose exec postgres psql -U openkb -d openkb -c "\dt"
```

Expected:
```
           List of relations
 Schema |      Name       | Type  |  Owner
--------+-----------------+-------+--------
 public | alembic_version | table | openkb
 public | documents       | table | openkb
 public | knowledge_bases | table | openkb
 public | wiki_pages      | table | openkb
(4 rows)
```

---

## Step 4 — Load seed data (optional)

```bash
python scripts/db_seed.py
```

Expected output:
```
[seed] Inserted knowledge_base: scratch-kb (id=<uuid>)
[seed] Inserted document: sample.pdf (id=<uuid>)
[seed] Inserted document: https://example.com/docs (id=<uuid>)
[seed] Done. 1 knowledge_base, 2 documents created.
```

Running the seed script a second time is safe — it skips already-existing records.

---

## Step 5 — Verify from Python

```python
# Quick smoke test — run from the repo root
import asyncio
from openkb.db import get_session
from openkb.db.metadata import knowledge_bases
from sqlalchemy import select

async def main():
    async with get_session() as session:
        result = await session.execute(select(knowledge_bases))
        rows = result.fetchall()
        print(f"knowledge_bases rows: {len(rows)}")

asyncio.run(main())
```

---

## Stopping the local environment

```bash
docker compose down          # Stop containers; data persists in pgdata volume
docker compose down -v       # Stop containers AND delete pgdata volume (clean reset)
```

---

## Running the test suite

```bash
# All DB tests (requires docker compose up first)
uv run pytest tests/db/ -v

# Schema validation only (fastest check)
uv run pytest tests/db/test_migrations.py -v

# Forward-compatibility check (SC-006)
uv run pytest tests/db/test_forward_compat.py -v
```

---

## Connecting with a GUI client

| Setting | Value |
|---------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `openkb` |
| User | `openkb` |
| Password | `openkb` |

Compatible with: TablePlus, DBeaver, pgAdmin, `psql`.

---

## Environment variable reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | Full async connection URL. See Step 2. |
| `POSTGRES_USER` | Docker only | Postgres superuser for the local container |
| `POSTGRES_PASSWORD` | Docker only | Postgres password for the local container |
| `POSTGRES_DB` | Docker only | Database name created on container start |

All variables are loaded automatically from `.env` by `python-dotenv` in development. In production, inject them as container environment variables or Key Vault references — never commit secrets.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `docker compose up` hangs | Postgres port 5432 in use | `lsof -i :5432` to find the conflicting process; or change `ports` in `docker-compose.yml` |
| `alembic upgrade head` fails with `relation already exists` | Partial schema from a previous run | `docker compose down -v && docker compose up --wait` |
| `Connection refused` from Python | Postgres not started or `.env` not loaded | Ensure `docker compose up --wait` completed; check `DATABASE_URL` in `.env` |
| Seed script inserts 0 rows | Seed data already present | Expected behaviour — the script is idempotent. Check with `psql -c "SELECT slug FROM knowledge_bases;"` |

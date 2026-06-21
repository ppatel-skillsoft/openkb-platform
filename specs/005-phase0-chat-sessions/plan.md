# Implementation Plan: Phase 0 Chat Session Assembly

**Branch**: `005-phase0-chat-sessions` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-phase0-chat-sessions/spec.md`

## Summary

Add multi-turn chat session support to the existing `generator-api` FastAPI service (spec 003) by
introducing 4 HTTP endpoints, 2 new Postgres tables (`chat_sessions`, `chat_messages`) via a new
Alembic migration, and a session-assembly service layer that prefixes recent conversation history
into every upstream sidecar query call. This is a pure extension of the existing service: same
FastAPI process, same port (8001), same Docker Compose stack — no new containers required.

The core intellectual work is the **session-assembly loop**: on each new message, fetch the last N
messages from Postgres, concatenate them as a labelled history prefix, call the existing query
sidecar path, persist both the user message and assistant response, then return the response to the
caller. Phase 0 success criterion: the second turn's answer demonstrably uses context from the
first turn.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: FastAPI (existing), SQLAlchemy Core 2.x + asyncpg (inherited from spec 001), httpx (inherited from spec 003 sidecar-spawn), Alembic (inherited from spec 001), Pydantic v2  
**Storage**: PostgreSQL 15-alpine (Docker Compose) — sole session store; no Redis in Phase 0  
**Testing**: pytest, pytest-asyncio, httpx `AsyncClient` (ASGI test mode)  
**Target Platform**: Linux container (Docker Compose); macOS standalone Python process for debugging  
**Project Type**: web-service (HTTP API extension to generator-api)  
**Performance Goals**: p95 end-to-end latency observable and logged; dominated by sidecar query time (typically 2–15 s); no specific SLA in Phase 0  
**Constraints**: No new containers; no Redis; no auth; no streaming; no session deletion endpoint; no user_id FK; history window configurable via env var (default 10 turns); assembled context ≤ token budget enforced by window cap alone  
**Scale/Scope**: Phase 0 local dev only — single developer, low volume, one KB instance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **Note**: The constitution file (`/.specify/memory/constitution.md`) contains only unfilled
> template placeholders — no operative principles have been ratified for this project yet.
> No constitution gates can be violated. Engineering defaults are applied in their place.

**Engineering defaults applied:**
- ✅ Local-first: all Phase 0 functionality runs without cloud credentials (Docker Compose only)
- ✅ No hardcoded credentials: all config via environment variables
- ✅ Test coverage: happy-path and error-path scenarios for all 4 endpoints
- ✅ Incremental migration: new Alembic revision builds on spec 001's `001_phase0_schema`
- ✅ Single-service extension: no new containers, no new processes; chat is part of generator-api

**Post-Phase 1 re-check**: See bottom of [data-model.md](./data-model.md) for gate re-evaluation.

## Project Structure

### Documentation (this feature)

```text
specs/005-phase0-chat-sessions/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions and rationale
├── data-model.md        # Phase 1 output — chat_sessions + chat_messages schema
├── quickstart.md        # Phase 1 output — end-to-end test walkthrough
├── contracts/
│   └── chat-http.md     # Phase 1 output — 4 endpoint HTTP contract
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Inherited Contracts (from prior specs)

These artefacts inform this plan but are produced by their own spec planning commands:

| Artefact | Source Spec | Key content consumed here |
|---|---|---|
| `db-session-factory.md` | spec 001 | Async `get_db_session()` dependency; `DATABASE_URL` env var |
| `data-model.md` (3 tables) | spec 001 | `knowledge_bases.id` UUID FK target |
| `generator-api-http.md` | spec 003 | `POST /kbs/{kb_id}/query` — sidecar proxy endpoint |
| `sidecar-spawn.md` | spec 003 | Sidecar HTTP call pattern; `SIDECAR_TIMEOUT` env var |
| `env-config.md` | spec 003 | `DATABASE_URL`, `BLOB_*`, `SIDECAR_*` env vars |
| `blob-storage-paths.md` | spec 002 | Container/blob path conventions (not directly used here) |

### Source Code Layout

```text
openkb/
├── api/
│   ├── __init__.py          # (exists — empty)
│   ├── app.py               # FastAPI app factory; include chat router (new)
│   ├── deps.py              # get_db_session() async dependency (new)
│   ├── models.py            # Pydantic request/response schemas (new + extend)
│   └── routes/
│       ├── __init__.py      # (exists — empty)
│       ├── kb.py            # Existing KB + query routes (spec 003)
│       └── chat.py          # 4 new chat endpoints (this feature)
├── db/
│   ├── __init__.py          # (new)
│   ├── session.py           # Async SQLAlchemy engine + session factory (spec 001)
│   └── migrations/
│       ├── alembic.ini      # (spec 001)
│       ├── env.py           # (spec 001)
│       └── versions/
│           ├── 001_phase0_schema.py      # knowledge_bases, documents, wiki_pages (spec 001)
│           └── 002_chat_tables.py        # chat_sessions, chat_messages (THIS feature)
└── services/
    ├── __init__.py
    ├── query_proxy_svc.py   # Sidecar proxy + wiki sync (spec 003)
    └── chat_session_svc.py  # Session CRUD + assembly loop (THIS feature)

tests/
├── integration/
│   ├── test_chat_sessions.py   # End-to-end: create session, send messages
│   └── test_chat_messages.py   # Message history, windowing, kb_id validation
└── unit/
    └── test_session_assembly.py # Assembly formatting logic in isolation
```

**Structure Decision**: Single Python package (`openkb/`) using an `api/routes/` router split and
a `services/` layer for business logic. Chat endpoints live in `api/routes/chat.py` and delegate
to `services/chat_session_svc.py`, which owns the assembly loop and Postgres interactions. This
keeps the route handlers thin and the assembly logic independently testable.

## Complexity Tracking

> No constitution violations to justify — constitution is an unfilled template.

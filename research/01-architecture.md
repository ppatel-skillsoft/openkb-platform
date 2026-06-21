# 01 — Architecture

## Upstream building block: OpenKB's FastAPI layer

OpenKB now has an HTTP API layer upstream (branch `001-fastapi-http-api`), wrapping the same engine the CLI uses. As of this writing it surfaces four operations: **`init`, `add`, `query`, `list`, `status`** — and has **no authentication**. This is good news for build speed and changes where our floor is, so it's worth being precise about what it does and doesn't give us before describing the services below.

What it gives us:
- HTTP transport already exists for the core engine — we are not writing the first HTTP wrapper around OpenKB's pipeline from scratch, which was originally scoped as Phase 0 in `10-roadmap-phasing.md`.
- It's presumably still **single-tenant / single-process**, assuming one local `wiki/` working tree per running instance, the same as the CLI — there's no indication it has any concept of multiple KBs per request, multiple orgs, or any request-scoped tenancy.
- FastAPI gives us OpenAPI/Swagger schema generation for free on whatever this layer exposes, which is useful for internal reference even though our own control-plane API (`06-api-spec.md`) is a distinct, superset surface.

What it does **not** give us, and what we still build ourselves:
- **No auth at all** — confirmed. Every concern in `03-auth-authn.md` and `04-authz-roles.md` is additive on top of this layer, not something to retrofit into it. Treat this upstream API as something that must never be exposed directly to the internet or to any tenant — it sits fully behind our `api`/`mcp-gateway` layer, never in front of it.
- **No `chat`** — only `query` is present. Multi-turn `chat` (stateful sessions, per `02-data-model.md`'s `chat_sessions`/`chat_messages`) is something we build, either as a contribution upstream or as a session-management layer in our own `generator-api` that makes repeated calls to upstream `query` with conversation context assembled on our side. Decide which during Phase 0 (see `10-roadmap-phasing.md`).
- **No `remove`, `recompile`, `watch`, or `lint`** in the HTTP surface (these exist in the CLI per OpenKB's README, just not yet exposed over HTTP as of this branch). Our `compiler-worker` either shells out to the CLI for these specific operations or waits for upstream to add them to the HTTP layer — don't block our roadmap on upstream's pace; subprocess fallback is fine for these less-latency-sensitive, less-frequent operations.
- **No Skill Factory** (`skill new`, `validate`, `eval`, `history`, `rollback`) over HTTP — same treatment as above, CLI subprocess fallback inside `compiler-worker` for now.
- **No multi-tenancy, no per-KB isolation, no job queue** — a single running instance of this API operates against one `wiki/` tree, same as the CLI did. Our `compiler-worker`/`generator-api` split is still the thing that makes this multi-tenant: we run (or call) this upstream layer per-KB, in a sandboxed/scoped way, rather than this layer ever becoming aware of tenancy itself.

Practical consequence for the build agent: treat the upstream FastAPI app as **the implementation detail inside `generator-api` (for `query`) and inside `compiler-worker` (for `add`, `init`, `list`, `status`)** — call it over HTTP to a locally-run sidecar process scoped to one KB's working tree, rather than reimplementing those four operations ourselves. This is a clean swap-in for the "OpenKB's existing Python package should be importable as a library" plan below — except now it's "importable as a sidecar HTTP service" instead, which is arguably easier to keep decoupled from upstream's internals as they evolve.

## High-level shape

OpenKB Enterprise has three layers, as introduced in `00-overview.md`:

```
                         ┌─────────────────────────────────────────────┐
                         │                Access Layer                  │
                         │   Web UI  │  REST API  │  MCP Servers (×KB)  │
                         └───────────────────┬───────────────────────────┘
                                              │
                         ┌────────────────────▼──────────────────────────┐
                         │               Platform Layer                   │
                         │  Auth/AuthZ │ Org/KB mgmt │ Job orchestration  │
                         │  Audit log  │ Usage metering │ Policy engine   │
                         └────────────────────┬──────────────────────────┘
                                              │
                         ┌────────────────────▼──────────────────────────┐
                         │            Compilation Engine (OpenKB core)    │
                         │  Upstream FastAPI sidecar: init/add/query/     │
                         │  list/status — per-KB, no auth, internal only  │
                         │  CLI fallback: remove/recompile/lint/skills    │
                         └────────────────────┬──────────────────────────┘
                                              │
                         ┌────────────────────▼──────────────────────────┐
                         │                  Storage                       │
                         │  Postgres (metadata) │ Blob (wiki+raw files)   │
                         │  Git (per-KB version history, optional)        │
                         └─────────────────────────────────────────────────┘
```

## Services

### 1. Control Plane API (`api`)
Stateless REST service (see `06-api-spec.md`). Owns org/user/KB/role/token CRUD, issues signed URLs for uploads, enqueues compilation jobs, serves the web UI's data needs, and is the thing the MCP servers call into for authorization checks. This is a normal multi-tenant SaaS backend — nothing OpenKB-specific lives here except KB/document metadata.

### 2. Compilation Workers (`compiler-worker`)
Pulls jobs off a queue (Azure Service Bus). Each job wraps an OpenKB operation: `init`, `add`, `recompile`, `remove`, `lint`. The worker:
- Pulls the raw file from Blob Storage into a scratch volume
- Runs a **per-job sidecar instance of OpenKB's upstream FastAPI app**, pointed at that scratch volume as its working `wiki/` tree, and calls its `init`/`add`/`list`/`status` endpoints over localhost HTTP — this replaces shelling out to the bare CLI for those four operations
- For operations not yet exposed over HTTP (`remove`, `recompile`, `lint`, Skill Factory commands), falls back to invoking the OpenKB CLI as a subprocess against the same scratch volume
- Writes the resulting markdown pages back to Blob Storage (and commits to the KB's Git history if enabled)
- Updates Postgres metadata (document status, which wiki pages were touched, token cost)
- Emits an audit event and a webhook/notification if configured

This worker is **stateless between jobs** — it spins up a fresh sidecar (or subprocess) against a scratch checkout of the KB's current wiki tree, operates, commits results back to Blob, and discards local state. This is what makes horizontal scaling and multi-tenancy safe: no worker holds long-lived state for a specific KB, and the upstream API's own lack of multi-tenancy is a non-issue because each sidecar instance only ever sees one KB's tree for the duration of one job.

Brief for the build agent: don't run one long-lived upstream API process shared across jobs/tenants — that would reintroduce exactly the single-tenant assumption the upstream layer carries. Spin up (or reuse from a small pool, scoped and torn down per job) a sidecar process per job, bind it to localhost only, and never let it accept traffic from anywhere but the worker process that owns it. As upstream adds auth and/or multi-tenancy in later branches, revisit whether the sidecar-per-job pattern is still the right shape — it may become possible to run fewer, longer-lived instances safely.

### 3. Generator Service (`generator-api`)
A thin service in front of OpenKB's generators — distinct from the compilation workers because generators are read-mostly, latency-sensitive, and called both from the web UI's chat playground and from MCP tool calls. Keeping it separate from `compiler-worker` means a slow document ingestion doesn't queue behind/compete with someone asking a question.

- `query`: proxied almost directly to the upstream FastAPI sidecar's `query` endpoint (scoped to one KB's working tree, same sidecar-per-request-or-small-pool pattern as `compiler-worker`, since the upstream layer has no multi-tenancy of its own) — stateless, takes a question + KB id, returns grounded answer + citations
- `chat`: **not present upstream as of this branch**, so this is ours to build — implemented as a session layer on top of repeated upstream `query` calls, with `generator-api` assembling conversation history from `chat_messages` (`02-data-model.md`) into the context sent to each `query` call, and persisting the new turn afterward. Session state lives in Postgres (or Redis for active session scratch + Postgres for durable history), keyed by `(kb_id, user_id, session_id)`. Revisit this approach if/when upstream adds native `chat` — at that point evaluate whether to switch to calling it directly versus keeping our own session-assembly layer (the latter may still be preferable if it needs to merge in things like collection-scoped access filtering that upstream won't know about).
- Skill Factory: not present upstream over HTTP; closer to a compilation job than a query anyway (it's a generation step that writes files), so it's queued through the same job system as `compiler-worker` and uses the CLI-subprocess fallback described there, just a different job type.

### 4. MCP Gateway (`mcp-gateway`)
One logical service, but **one MCP endpoint per KB** (`https://api.yourapp.com/mcp/{kb_id}`), not a single global endpoint multiplexing KBs by parameter. This matters for:
- OAuth scoping — a token issued for KB A's endpoint should be structurally incapable of being replayed against KB B
- Rate limiting — per-KB limits, not a shared bucket
- Audit clarity — every log line already carries the KB id from the URL, not from a trusted-but-spoofable parameter

The gateway validates the MCP OAuth token, resolves it to the user who authorized it, and checks the policy engine (see `04-authz-roles.md`) for what that user's role allows — narrowed unconditionally to the fixed read-only tool set, regardless of role — then proxies the actual tool call to `generator-api`. There is no write path through this gateway at all; document operations live only behind `api`, reached via the authenticated web UI/control-plane API, never via an MCP token. Full design in `05-mcp-integration.md`.

### 5. Policy Engine
Not a separate network service initially — a library used by `api`, `generator-api`, and `mcp-gateway`, backed by the `permissions` table (see `02-data-model.md`). Answers one question: *can subject X do action Y on resource Z?* Centralizing this as a library with one call signature, rather than duplicating role checks in three services, is what keeps `04-authz-roles.md`'s policy-as-data principle actually true in practice. If/when policy logic outgrows a library (e.g. you need cross-service caching of decisions at scale), extract it into its own service — but don't start there.

## Data flow: adding a document

```
User/agent uploads file
   → api issues Blob SAS URL, client uploads directly to Blob
   → api creates `documents` row (status: pending), enqueues compile job to Service Bus
   → compiler-worker picks up job
       → downloads raw file from Blob
       → markitdown (short) or PageIndex (long PDF) conversion
       → LLM compiles: summary page, concept pages touched/updated, entity pages touched/updated
       → writes wiki/*.md back to Blob; commits to Git if enabled
       → updates `documents` row (status: complete), `wiki_pages` rows, token-cost ledger
       → audit event: document.compiled
   → api notifies client (websocket/poll) — UI shows status transition
```

## Data flow: agent query via MCP

```
Agent (e.g. Claude Code) connects to https://api.yourapp.com/mcp/{kb_id}
   → OAuth handshake; user logs in (if not already) and approves "read-only access to this KB"
   → api_tokens row created: user_id = the logged-in user, kb_id, read_only = true
   → mcp-gateway checks policy engine: does this user have Viewer+ on kb_id? (the only check that matters — role beyond Viewer grants nothing extra over MCP)
   → tool call kb_query("question") proxied to generator-api
   → generator-api runs OpenKB's query generator against the KB's compiled wiki
   → response (answer + citations) returned to agent
   → audit event logged: { actor_id: user_id, via: 'mcp', kb_id, tool, tokens_used }
```

## Why Postgres + Blob, not a vector DB

OpenKB is explicitly vectorless — retrieval is via PageIndex's reasoning-based tree index and the LLM reading compiled wiki pages directly, not embedding similarity search. We are not introducing a vector DB into this architecture. Postgres holds structured metadata (orgs, users, documents, permissions, audit, usage); Blob Storage holds the actual wiki content as markdown files (consistent with OpenKB's own design, and it's what makes the Obsidian-compatibility and Git-versioning stories work for free). If a future product need genuinely requires embedding search (e.g. similarity search across thousands of KBs for some federated-search feature), evaluate it as an addition at that point — don't pre-build it.

## Multi-tenancy isolation

- **Storage**: each KB gets its own Blob container or container-prefix (`kb-{kb_id}/raw/`, `kb-{kb_id}/wiki/`). No cross-KB path traversal possible by construction.
- **Compute**: compiler-worker and generator-api are stateless per-job/per-request, so tenant isolation is enforced by the KB id passed into each job, not by infrastructure-level sandboxing. This is sufficient because there's no shared mutable state between tenants at the process level.
- **Database**: row-level tenancy via `org_id`/`kb_id` foreign keys, not separate schemas-per-tenant — simpler operationally, and Postgres row-level security (RLS) policies can be layered on as defense-in-depth once the core product is stable.
- **LLM calls**: each org can configure its own LLM provider keys (BYO Azure OpenAI deployment, Bedrock, etc.) — see `08-admin-ops.md`. Even on the default shared-key path, requests should carry org/KB context in a way that supports per-org cost attribution.

## Open architectural questions to resolve during build

These are flagged, not answered, because they need a decision against real constraints (cost targets, expected KB sizes) that aren't settled yet:

- Whether `chat` session state lives in Redis-with-Postgres-backup or Postgres-only — depends on expected concurrent session volume.
- Whether per-KB Git history is on by default or opt-in (it's valuable for audit/rollback but adds storage and operational surface).
- Whether compilation jobs for very large document batches need a sub-job/fan-out model, or whether one job per document is fine at expected scale.
- Sidecar lifecycle for the upstream FastAPI layer: spin-up-per-job (simplest, safest isolation, but pays process-start latency on every `query`) versus a small warm pool of sidecars checked out/in per KB (faster, but reintroduces some shared-process risk the per-job model avoids, and needs its own scoping logic to make sure a pooled instance is never reused across KBs without a clean working-tree swap). Start with per-job/per-request for Phase 0 correctness; revisit if `query` latency under the spin-up cost proves unacceptable.

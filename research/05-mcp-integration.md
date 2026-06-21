# 05 — MCP Integration

This is the product's differentiator relative to plain OpenKB, which only ships a read-only agent *skill* file (static instructions an agent reads), not a live, access-controlled MCP server. This document specifies the MCP server design referenced in `01-architecture.md`'s `mcp-gateway` service.

## Design tenets

1. **One MCP endpoint per KB.** `https://api.yourapp.com/mcp/{kb_id}`. Not a single global endpoint with a KB selector parameter inside tool calls — see `01-architecture.md` for why (OAuth scoping, rate limiting, audit clarity all get structurally simpler).
2. **OAuth 2.1 is the only auth path** for MCP, per `03-auth-authn.md`. No static API key fallback for this specific surface — MCP tokens always trace back to one explicit OAuth grant by one named user.
3. **An agent acts as the connecting user, not as a separate principal.** There is no agent/machine identity (`03-auth-authn.md`, `04-authz-roles.md`). Every MCP call is logged and permissioned against the human who authorized the connection.
4. **The entire MCP tool surface is read-only, unconditionally.** Not "read-only by default" or "read-only unless granted otherwise" — there is no write-capable MCP tool in this product, for any role, full stop. See `04-authz-roles.md` for why this is a hard rule rather than a configurable default.
5. **Tools mirror OpenKB's read-side generators** — `query`, `chat`, list/status, entity search. Consistency with the CLI's mental model matters for anyone who's used OpenKB directly.
6. **Citations are non-negotiable in tool output.** Every answer-producing tool returns structured citation data, not just prose with inline references that get lost in agent context.

## Tool surface

Every tool below is reachable by any user with at least Viewer access to the KB — there's no tool-by-tool permission tiering, because none of these tools write, and "can you see this KB at all" is the only gate that matters.

### `kb_query`
- **Input**: `question: string`, optional `save: boolean` (persists to `wiki/explorations/`, mirrors `openkb query --save`)
- **Output**: `{ answer: string, citations: [{document_id, wiki_page_id, page_type, excerpt}], tokens_used }`
- **Behavior**: stateless, single question → single answer, proxied to `generator-api`, which itself proxies directly to upstream OpenKB's `query` endpoint (`01-architecture.md`) — this tool is the closest 1:1 mapping onto what already exists upstream today.

### `kb_chat`
- **Input**: `message: string`, `session_id: string | null` (omit to start a new session)
- **Output**: `{ session_id, response: string, citations: [...], tokens_used }`
- **Behavior**: stateful, backed by `chat_sessions`/`chat_messages` (`02-data-model.md`), tied to the connecting user's `user_id`. A user's MCP-driven chat session and their web-UI chat session are both just sessions owned by that `user_id` (distinguished only by the `via` field) — an agent cannot resume a session belonging to a different user, since session ownership is checked the same way regardless of channel. Note: upstream OpenKB does not have a `chat` endpoint as of the current branch — this tool is backed entirely by our own session-assembly layer in `generator-api`, which calls upstream `query` once per turn with accumulated context (`01-architecture.md`). Treat this tool as higher build priority for us specifically because it's not "free" from upstream the way `kb_query` is.

### `kb_list_documents`
- **Input**: optional `collection_id` filter
- **Output**: array of `{document_id, filename, status, collection, added_at}`
- **Behavior**: results filtered to collections the connecting user has at least Viewer on, if collection-scoped grants are in play.

### `kb_status`
- **Output**: document count, last compilation time, wiki page counts by type — mirrors `openkb status`

### `kb_search_entities`
- **Input**: `name: string`, optional `entity_type` filter
- **Output**: matching entity pages with summaries
- **Behavior**: surfaces OpenKB's entity-page feature (people/orgs/places/products) as a structured lookup, useful for agents doing entity resolution rather than free-text query.

## No write tools — by design, not by omission

There is intentionally no `kb_add_document`, no `kb_generate_skill`, no `kb_remove_document`, no wiki-edit tool anywhere in this surface. This isn't a v1 limitation waiting to be lifted in a later phase — see `04-authz-roles.md`'s permission matrix, which marks every write action as unconditionally `❌ never` via MCP regardless of role. To add a document, generate a skill, or edit a wiki page, a user goes through the web UI or the authenticated control-plane API (`06-api-spec.md`), both of which require an active human session rather than an MCP bearer token.

If a future product need genuinely requires agent-driven writes (e.g. an automated ingestion pipeline), treat that as a new, separate, carefully-scoped feature with its own threat model — not an incremental loosening of the existing MCP token's `read_only` flag (`02-data-model.md`).

## OAuth flow specifics

Already outlined in `03-auth-authn.md`; the MCP-specific details:

- `mcp-gateway` implements the MCP authorization spec's discovery endpoints (`/.well-known/oauth-protected-resource` etc.) pointing at the platform's OAuth authorization server (could be the same `api` service or a dedicated auth service — implementation detail, not a product decision).
- The consent screen shown mid-flow must clearly state which KB and that the access being granted is **read-only** — there's no permission-level choice to present, since there's only one possible outcome, which actually makes this screen simpler than a typical OAuth consent dialog. Don't ask the user to pick a scope; tell them what they're getting.
- Dynamic client registration (per MCP spec) should be supported so popular MCP clients (Claude, Claude Code, Claude Desktop) can self-register without the org admin pre-registering every possible client app manually.
- Every issued token's `user_id` is exactly the user who completed the consent flow — never an org admin granting access on someone else's behalf, since that would break the "this is always the connecting user's own access" property the whole model rests on.

## Rate limiting & quota

- Per-user rate limits on MCP calls (requests/minute), separate from per-KB limits — an aggressive single connection shouldn't be able to exhaust a KB's quota for every other connected user.
- Token-cost-based quota as a second dimension, since `kb_query`/`kb_chat` consume LLM tokens — surfaced in `usage_ledger` and visible to org admins (`08-admin-ops.md`), with optional hard caps configurable per KB or per user to prevent runaway cost from a misbehaving agent loop.
- 429 responses on MCP tool calls should include enough detail (reset time, current usage) for a well-behaved agent to back off gracefully.

## Audit logging specifics for MCP

Every MCP tool call writes an `audit_log` row (`02-data-model.md`) with at minimum: `actor_id` (the user), `via='mcp'`, KB id, tool name, input summary (not necessarily full input if it contains sensitive document content — log a hash/reference for large payloads, full text for short ones, configurable retention), token cost, and result status. This is the data the admin console's "MCP activity" view is built from (`08-admin-ops.md`) — since there's no separate agent identity, this view is really "which of our users' MCP connections are doing what," filterable by user.

## What MCP does not do

- MCP is not the file-upload transport, and was never going to be, since there's no write path at all on this surface now.
- MCP is not where org/KB administration happens (creating KBs, managing `kb_access` grants, configuring SSO) — that's the REST API / web UI only (`06-api-spec.md`, `07-web-ui-ux.md`), and always requires an authenticated human session, never an MCP bearer token.

## Relationship to OpenKB's existing Skill (non-MCP path)

OpenKB already ships a static `SKILL.md` that agents can install to read a *local filesystem* wiki read-only, with no auth, no multi-tenancy — fine for a single developer's local KB, not viable for an enterprise-shared one. Keep both paths available, scoped to their right use case: the static skill remains useful for "I have local files and want my local agent to read them," while MCP is the path for "I want an agent, acting as me, to query a centrally managed, access-controlled KB I have access to." Both paths are read-only, which is a nice consistency point — don't deprecate the static skill; document when to use which.

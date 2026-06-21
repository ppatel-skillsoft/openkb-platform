# 06 — API Specification (Control Plane)

REST API served by the `api` service (`01-architecture.md`). This is the surface the web UI is built on, and the surface MCP tool calls proxy through for anything beyond `query`/`chat`. Conventions: JSON, bearer auth (session JWT for human/UI calls, API token for programmatic calls), standard HTTP status codes, cursor-based pagination on list endpoints (`?cursor=...&limit=...`).

This is not an exhaustive OpenAPI document — it's the endpoint inventory and the decisions that matter for an agent building it. Generate the full OpenAPI spec from this once routes are stable.

**Relationship to upstream OpenKB's FastAPI layer**: this control-plane API is a distinct, multi-tenant, authenticated surface — it is *not* the same thing as upstream's `001-fastapi-http-api` branch, which is unauthenticated and single-tenant (see `01-architecture.md`). Several endpoints below are thin, auth-and-tenancy-wrapped passthroughs to that upstream layer (called via the per-KB sidecar pattern); others (everything access-control-related, plus `chat`, `recompile`, `remove`, Skill Factory) are ours alone because upstream doesn't have them yet. Each relevant section below notes which case it is.

## Auth

```
POST   /auth/login                  email+password (disabled if org has sso_enforced)
POST   /auth/sso/{provider}/start    begins OIDC/SAML redirect
GET    /auth/sso/{provider}/callback
POST   /auth/refresh                 rotate refresh token
POST   /auth/logout
```

## Organizations

```
GET    /orgs/{org_id}
PATCH  /orgs/{org_id}                 owner/admin only
DELETE /orgs/{org_id}                 owner only; soft delete + grace period before hard purge
GET    /orgs/{org_id}/members
POST   /orgs/{org_id}/members/invite
PATCH  /orgs/{org_id}/members/{user_id}    change org_role, or remove
GET    /orgs/{org_id}/sso-config
PUT    /orgs/{org_id}/sso-config           admin only; secrets write-only, never returned in GET
```

## Knowledge bases

```
GET    /orgs/{org_id}/kbs
POST   /orgs/{org_id}/kbs                  creates KB, creator becomes Owner via kb_access
GET    /kbs/{kb_id}
PATCH  /kbs/{kb_id}                        name/description/compilation_config; Owner only
DELETE /kbs/{kb_id}                        Owner only; cascades per 02-data-model.md
GET    /kbs/{kb_id}/status                 doc/page counts, last compile time — mirrors `openkb status`
```

### Collections

```
GET    /kbs/{kb_id}/collections
POST   /kbs/{kb_id}/collections            Owner only
PATCH  /kbs/{kb_id}/collections/{id}
DELETE /kbs/{kb_id}/collections/{id}       documents become uncategorized, not deleted
```

### Documents

```
GET    /kbs/{kb_id}/documents              filterable by collection_id, status   — backed by upstream `list`/`status`
POST   /kbs/{kb_id}/documents/upload-url   returns a signed Blob SAS URL for direct client upload
POST   /kbs/{kb_id}/documents               registers a document after upload (or with a source URL), enqueues compile job — job calls upstream `add`
GET    /kbs/{kb_id}/documents/{doc_id}
DELETE /kbs/{kb_id}/documents/{doc_id}     Editor+; enqueues removal job — no upstream HTTP `remove` yet, worker uses CLI fallback (`01-architecture.md`)
POST   /kbs/{kb_id}/documents/{doc_id}/recompile   Editor+ — no upstream HTTP `recompile` yet, CLI fallback
```

The two-step upload (`upload-url` then `documents` registration) keeps large file bytes off the API service entirely — client uploads straight to Blob, API only ever sees metadata and a path. Mirrors `01-architecture.md`'s data flow. The `documents` POST is also what triggers `compiler-worker` to run upstream's `init` (if the KB's working tree doesn't exist yet in the job's scratch volume) followed by `add`.

### Wiki pages

```
GET    /kbs/{kb_id}/wiki-pages             filterable by page_type, slug
GET    /kbs/{kb_id}/wiki-pages/{page_id}   includes content + contributing documents (wiki_page_documents)
PATCH  /kbs/{kb_id}/wiki-pages/{page_id}   manual edit; Editor+; flags the page as manually-edited so a future recompile warns before overwrite
POST   /kbs/{kb_id}/lint                   mirrors `openkb lint`; returns structural + knowledge health report
```

### Query & chat (also exposed as MCP tools — see `05-mcp-integration.md`)

```
POST   /kbs/{kb_id}/query                  { question, save? } → { answer, citations, tokens_used }   — proxied to upstream `query`
POST   /kbs/{kb_id}/chat/sessions          starts a session       — ours; no upstream equivalent
POST   /kbs/{kb_id}/chat/sessions/{id}/messages                   — ours; assembles history + calls upstream `query` per turn (`01-architecture.md`)
GET    /kbs/{kb_id}/chat/sessions          list (own sessions only, unless Owner)
GET    /kbs/{kb_id}/chat/sessions/{id}
DELETE /kbs/{kb_id}/chat/sessions/{id}
```

### Skill Factory

```
POST   /kbs/{kb_id}/skills                 { skill_name, intent } → { job_id } (async, Contributor+)
GET    /kbs/{kb_id}/skills
GET    /kbs/{kb_id}/skills/{name}
POST   /kbs/{kb_id}/skills/{name}/validate
POST   /kbs/{kb_id}/skills/{name}/eval
GET    /kbs/{kb_id}/skills/{name}/history
POST   /kbs/{kb_id}/skills/{name}/rollback   { to_iteration }
```

Web UI / control-plane API only — not exposed as an MCP tool, since it's a write/generation action and the entire MCP surface is read-only (`04-authz-roles.md`, `05-mcp-integration.md`).

## Access control

```
GET    /kbs/{kb_id}/access                 list all kb_access grants (Owner only)
POST   /kbs/{kb_id}/access                 grant { user_id, role, collection_id?, expires_at? }
PATCH  /kbs/{kb_id}/access/{grant_id}      change role/expiry — does NOT apply to issued tokens retroactively (03-auth-authn.md: a token's read_only/kb_id binding is fixed at issuance; this only governs future permission checks)
DELETE /kbs/{kb_id}/access/{grant_id}      revoke
```

## API tokens (own tokens — MCP connections and manual PATs)

```
GET    /users/me/tokens                    list the current user's own tokens (both oauth_mcp and manual_pat), with label, kb_id, last_used_at, expires_at
POST   /users/me/tokens                    issue a manual_pat (self-service; oauth_mcp tokens are issued only via the OAuth flow in 05-mcp-integration.md, not this endpoint)
PATCH  /users/me/tokens/{token_id}         rename label only — role/scope/read_only are immutable post-issuance
DELETE /users/me/tokens/{token_id}         revoke own token
```

```
GET    /orgs/{org_id}/tokens               org-admin view of every issued token across the org's users, filterable by user, kb_id, issued_via — for offboarding/incident response (08-admin-ops.md)
DELETE /orgs/{org_id}/tokens/{token_id}    admin-initiated revocation of any user's token
```

There is no separate agent-identity object or endpoint set. Every token in this system belongs to exactly one `user_id`; connecting an MCP client is just one particular way a token gets issued (`issued_via = 'oauth_mcp'`), not a different kind of object (`02-data-model.md`, `03-auth-authn.md`).

## Audit & usage

```
GET    /orgs/{org_id}/audit-log            filterable by kb_id, actor_id, via, action, date range
GET    /orgs/{org_id}/usage                 aggregated usage_ledger, filterable by kb_id, date range, group-by
GET    /kbs/{kb_id}/usage
```

## LLM provider config

```
GET    /orgs/{org_id}/llm-configs
POST   /orgs/{org_id}/llm-configs          { provider, model, credential_ref } — admin only; credential goes straight to Key Vault, API never stores or returns raw key
PATCH  /kbs/{kb_id}                        (existing endpoint) llm_provider_config_id field overrides org default per-KB
```

## Webhooks (outbound, for async job notification)

```
GET    /orgs/{org_id}/webhooks
POST   /orgs/{org_id}/webhooks             { url, events: ["document.compiled", "document.failed", "skill.generated", ...] }
DELETE /orgs/{org_id}/webhooks/{id}
```

Used so a client doesn't have to poll `GET /documents/{id}` for compilation status — relevant for both the web UI (websocket preferred there, see `07-web-ui-ux.md`) and for programmatic/agent-driven document ingestion at volume.

## Error shape

Consistent across all endpoints:

```json
{
  "error": {
    "code": "kb_access_denied",
    "message": "Human-readable explanation",
    "details": { }
  }
}
```

Error codes should be stable strings (not just HTTP status), since MCP tool error surfaces and the web UI both need to branch on them programmatically, not just display the message.

## Versioning

Path-prefix versioning (`/v1/...`) from day one even though there's only one version initially — retrofitting versioning into a live API used by both a web UI and external MCP/agent integrations is significantly more painful than starting with it.

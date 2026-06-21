# 02 — Data Model

## Conventions

- All primary keys are UUIDs (`gen_random_uuid()`).
- All tables have `created_at`, `updated_at` timestamps; soft-delete via `deleted_at` (nullable) rather than hard deletes, except where noted — enterprise customers will ask "can you recover what we deleted."
- Foreign keys are explicit and indexed.
- This schema is Postgres-flavored (Azure Database for PostgreSQL Flexible Server — see `09-deployment.md`).
- **Single principal type.** There is no machine/agent identity table. Every actor in the system — whether a human clicking through the web UI or an MCP client (Claude, Claude Code, etc.) calling on someone's behalf — is a row in `users`. See `00-overview.md` and `03-auth-authn.md` for why this was a deliberate simplification, not an oversight.

## Entity overview

```
organizations ──< org_members >── users
      │
      ├──< knowledge_bases ──< documents ──< wiki_pages
      │         │
      │         ├──< collections
      │         ├──< kb_access (role grants — per user)
      │         └──< chat_sessions
      │
      ├──< api_tokens
      ├──< audit_log
      ├──< usage_ledger
      └──< sso_config
```

## Core tables

### `organizations`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | |
| slug | text unique | URL-safe identifier |
| plan | text | e.g. `free`, `team`, `enterprise` |
| sso_enforced | boolean | if true, password login disabled org-wide |
| default_llm_provider_config_id | uuid FK → `llm_provider_configs` | nullable; falls back to platform default |
| created_at, updated_at, deleted_at | timestamptz | |

### `users`
The only principal type in the system — see "single principal type" above.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | text unique | |
| display_name | text | |
| auth_provider | text | `password`, `entra_id`, `okta`, `google` |
| external_subject_id | text | nullable; the IdP's `sub` claim for SSO users |
| status | text | `active`, `invited`, `suspended` |
| last_login_at | timestamptz | |
| created_at, updated_at, deleted_at | | |

### `org_members`
Join table; a user's role *within* an org (separate from KB-level roles).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | |
| user_id | uuid FK → users | |
| org_role | text | `owner`, `admin`, `member`, `billing` — see `04-authz-roles.md` |
| invited_by | uuid FK → users | nullable |
| created_at, updated_at | | |
| | | unique (org_id, user_id) |

### `knowledge_bases`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | |
| name | text | |
| slug | text | unique within org |
| description | text | |
| storage_container_path | text | e.g. `kb-{id}/` in Blob |
| git_versioning_enabled | boolean | default true |
| llm_provider_config_id | uuid FK → llm_provider_configs | nullable; overrides org default |
| compilation_config | jsonb | `{ language, pageindex_threshold, entity_types, extra_headers }` — mirrors OpenKB's `config.yaml` |
| status | text | `active`, `archived` |
| created_by | uuid FK → users | |
| created_at, updated_at, deleted_at | | |

### `collections`
Sub-grouping within a KB for finer-grained access control than all-or-nothing at KB level.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| kb_id | uuid FK → knowledge_bases | |
| name | text | e.g. "HR Policies", "Public Docs" |
| sensitivity_label | text | nullable; e.g. `internal`, `confidential` — informational, enforcement is via `kb_access` |
| created_at, updated_at | | |

### `documents`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| kb_id | uuid FK → knowledge_bases | |
| collection_id | uuid FK → collections | nullable — uncategorized if null |
| source_type | text | `pdf`, `docx`, `pptx`, `xlsx`, `html`, `md`, `csv`, `url`, `text` |
| source_uri | text | Blob path or original URL |
| original_filename | text | |
| status | text | `pending`, `compiling`, `complete`, `failed` |
| failure_reason | text | nullable |
| pageindex_used | boolean | true if routed through PageIndex (long PDF path) |
| token_cost | integer | nullable; LLM tokens consumed compiling this doc |
| added_by | uuid FK → users | the human who added this document — always a user, via the web UI or control-plane API; never via MCP, see `04-authz-roles.md` |
| created_at, updated_at, deleted_at | | |

### `wiki_pages`
Tracks which compiled pages exist and which document(s) touched them — needed because OpenKB's compilation is cross-document (one doc can update many existing concept/entity pages).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| kb_id | uuid FK → knowledge_bases | |
| page_type | text | `summary`, `concept`, `entity`, `index`, `exploration` |
| slug | text | matches the markdown filename / wikilink target |
| blob_path | text | |
| entity_type | text | nullable; for entity pages — `person`, `organization`, `place`, `product`, `work`, `event`, `other` |
| last_compiled_at | timestamptz | |
| | | unique (kb_id, slug) |

### `wiki_page_documents`
Many-to-many: which documents contributed to/touched which wiki page (for "why does this page say this" traceability).

| Column | Type | Notes |
|---|---|---|
| wiki_page_id | uuid FK → wiki_pages | |
| document_id | uuid FK → documents | |
| | | PK (wiki_page_id, document_id) |

### `chat_sessions`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | matches OpenKB's session id format where reasonable |
| kb_id | uuid FK → knowledge_bases | |
| user_id | uuid FK → users | the session owner — whether driven from the web UI or from an MCP-connected agent acting as this user, it's the same user_id and the same row |
| via | text | `web`, `mcp` — descriptive only; carries no permission implication, since permissions are identical either way (`04-authz-roles.md`) |
| title | text | nullable; auto-generated from first message |
| created_at, updated_at, deleted_at | | |

### `chat_messages`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| session_id | uuid FK → chat_sessions | |
| role | text | `user`, `assistant` |
| content | text | |
| citations | jsonb | array of `{wiki_page_id, document_id, excerpt_ref}` |
| token_cost | integer | |
| created_at | | |

## Identity & access tables

### `kb_access`
The core ACL table — grants a role on a specific KB (or collection) to a user. This is the policy-as-data table referenced throughout. There is no agent/machine variant — a grant belongs to a user, full stop; an MCP-connected agent calling on that user's behalf operates under this exact same grant, further constrained to read-only by the token itself (`03-auth-authn.md`, `04-authz-roles.md`).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| kb_id | uuid FK → knowledge_bases | |
| collection_id | uuid FK → collections | nullable; if set, grant is scoped to this collection only |
| user_id | uuid FK → users | |
| role | text | `owner`, `editor`, `contributor`, `viewer` — see `04-authz-roles.md` |
| granted_by | uuid FK → users | |
| expires_at | timestamptz | nullable — supports time-boxed access grants (e.g. a contractor) |
| created_at, updated_at | | |
| | | unique (kb_id, collection_id, user_id) |

### `api_tokens`
Issued tokens — both for human PAT-style use and as the persisted record behind MCP OAuth grants (the actual bearer secret is hashed, never stored plaintext). Every token belongs to exactly one user. A token never carries its own independent permission grant; it inherits whatever that user's `kb_access` already allows, intersected with the token's own `read_only` flag.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | |
| user_id | uuid FK → users | |
| label | text | nullable, user-supplied; e.g. "Claude Code — laptop" — purely descriptive for the user's own audit clarity, not a separate identity (`03-auth-authn.md`) |
| token_hash | text | SHA-256 of the actual token; never store plaintext |
| token_prefix | text | first 8 chars, shown in UI for identification |
| issued_via | text | `oauth_mcp`, `manual_pat` |
| kb_id | uuid FK → knowledge_bases | nullable for `manual_pat` (may be broader); always set for `oauth_mcp` — every MCP token is scoped to exactly one KB |
| read_only | boolean | always `true` for `issued_via = 'oauth_mcp'`, enforced server-side at issuance, not just a client-side convention — see `03-auth-authn.md` |
| expires_at | timestamptz | nullable |
| revoked_at | timestamptz | nullable |
| last_used_at | timestamptz | |
| created_at | | |

### `sso_config`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | unique |
| provider | text | `entra_id`, `okta`, `google`, `generic_oidc`, `saml` |
| config | jsonb | provider metadata URL, client id, etc. (secrets stored in Key Vault, referenced not embedded — see `09-deployment.md`) |
| enforced | boolean | mirrors `organizations.sso_enforced`, kept here for provider-specific detail |
| created_at, updated_at | | |

## Operational tables

### `audit_log`
Append-only; never updated or soft-deleted (retention policy handles expiry, not application logic).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | |
| kb_id | uuid FK → knowledge_bases | nullable (some events are org-level) |
| actor_id | uuid FK → users | nullable for system-generated events |
| via | text | `web`, `api`, `mcp`, `system` — how the action was taken; an MCP-originated query and a web-UI-originated query from the same user both log the same `actor_id`, distinguished only by this field |
| action | text | e.g. `document.added`, `kb_access.granted`, `mcp.query`, `sso.config_changed` |
| resource_type | text | |
| resource_id | uuid | |
| metadata | jsonb | action-specific detail |
| ip_address | inet | nullable |
| created_at | timestamptz | |

Indexed on `(org_id, created_at)` and `(kb_id, created_at)` for the admin console's audit viewer (`08-admin-ops.md`).

### `usage_ledger`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | |
| kb_id | uuid FK → knowledge_bases | |
| event_type | text | `compilation`, `query`, `chat_message`, `skill_generation` |
| llm_provider | text | |
| llm_model | text | |
| input_tokens | integer | |
| output_tokens | integer | |
| estimated_cost_usd | numeric(10,4) | |
| user_id | uuid FK → users | |
| via | text | `web`, `mcp` |
| created_at | | |

### `llm_provider_configs`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | nullable — null means platform-default config |
| provider | text | `azure_openai`, `openai`, `anthropic`, `bedrock`, `vertex` |
| model | text | LiteLLM `provider/model` format, e.g. `anthropic/claude-sonnet-4-6` |
| credential_ref | text | Key Vault secret reference, never raw key in DB |
| extra_headers | jsonb | nullable |
| created_at, updated_at | | |

## What changed from earlier drafts, and why

An earlier version of this schema included an `agent_identities` table and polymorphic `subject_type`/`actor_type` columns (`'user' | 'agent_identity'`) across `kb_access`, `api_tokens`, `chat_sessions`, `audit_log`, and `usage_ledger`, treating an MCP-connected agent as a distinct machine principal from the human who deployed it. That model is **removed**. The product decision is: an agent calling via MCP always acts as the human user who authorized it, using that user's own `kb_access` grants, with no independent identity or permission surface of its own — and every MCP-issued token is read-only by construction regardless of what the underlying user could otherwise do (`03-auth-authn.md`, `04-authz-roles.md`). This is a meaningfully simpler model — one principal type, one grant table, no polymorphic associations — and removes an entire class of "does this agent identity's permission correctly stay bounded by its creator's permission" reasoning that the earlier design required.

## Notes on `via` columns

Several tables above (`chat_sessions`, `audit_log`, `usage_ledger`) carry a `via` field (`web`/`api`/`mcp`/`system`) even though there's only one principal type. This is deliberate and worth distinguishing from the polymorphic-subject pattern that was removed: `via` is **purely descriptive metadata** for analytics and audit legibility ("show me this user's MCP activity specifically"), and no authorization decision anywhere reads it for KB-level permission — a query's *permission outcome* is governed by the user's `kb_access` role exactly the same way regardless of `via`. The one place `via`-equivalent state does matter is `api_tokens.read_only`, which is a property of the token, not of the `via` label, and is what actually enforces the read-only constraint on MCP calls (`03-auth-authn.md`, `04-authz-roles.md`).

## What's deliberately not in v1 schema

- No per-field/per-paragraph ACLs inside a single wiki page — collection-level is the finest grain initially (see `04-authz-roles.md` for why).
- No multi-region replication tables — single-region Azure deployment first (see `09-deployment.md`).
- No separate `teams`/`groups` table for bulk role assignment — `kb_access` grants are per-user initially; groups are a clear v2 addition once usage patterns are clearer (see `10-roadmap-phasing.md`).

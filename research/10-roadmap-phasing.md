# 10 — Roadmap & Phasing

Build order. This is deliberately not in the same order as the rest of the document set — reading order (00→09) front-loads concepts you need to understand the whole system; build order front-loads the smallest thing that proves the architecture works, then layers in the parts that make it an actual enterprise product.

## Phase 0 — Prove the wrap (single-tenant)

**Status: substantially de-risked.** Upstream OpenKB's `001-fastapi-http-api` branch already wraps the core engine in an HTTP layer (`init`, `add`, `query`, `list`, `status`, no auth) — see `01-architecture.md`. This phase is now mostly *integration and validation* of that upstream layer inside our own service shape, rather than building an HTTP wrapper from zero.

**Goal**: confirm the upstream FastAPI layer can run as a per-job/per-KB sidecar inside our worker and generator services, before any multi-tenancy/auth complexity gets added on top.

- Stand up Postgres (`02-data-model.md`'s `documents`, `wiki_pages`, `knowledge_bases` tables only — skip org/user/access tables for now) and Blob Storage.
- Wrap `compiler-worker` around the upstream FastAPI sidecar pattern (`01-architecture.md`): pull a job, spin up the sidecar against a scratch volume, call `init`/`add`, push results to Blob. Single hardcoded KB, no auth, internal use only.
- Confirm: upload a doc → job runs → wiki pages land in Blob → metadata lands in Postgres, matching what the upstream API (and the underlying CLI) produces directly against the same file.
- Stand up `generator-api` proxying `query` to the same sidecar pattern.
- **New work this phase, since it's not upstream**: a first pass at `chat` as a session-assembly layer over repeated `query` calls (`01-architecture.md`) — even a rough version is useful to validate early, since it's the one generator we don't get for free.
- Validate the sidecar isolation assumption explicitly: confirm that two concurrent jobs against two different KBs, each with their own sidecar instance, never cross-contaminate (no shared working directory, no port collision, no shared process state) — this is the thing that makes an unauthenticated single-tenant upstream layer safe to build on top of.

**Exit criterion**: a document compiled through our service produces the same wiki output as running OpenKB directly (CLI or upstream API) against the same file, `query` returns the same quality of grounded answer, and a first-pass `chat` can hold a coherent two-turn conversation using assembled context.

## Phase 1 — Multi-tenancy + human auth

- Add full `02-data-model.md` schema: `organizations`, `users`, `org_members`, `knowledge_bases` (now properly org-scoped), `collections`.
- Implement human authentication (`03-auth-authn.md`): email/password first, Entra ID SSO second (don't block Phase 1 exit on SSO if it's slower to wire up — password auth alone is enough to validate multi-tenancy).
- Implement org-level and KB-level roles (`04-authz-roles.md`) with the policy engine as a library (`01-architecture.md`).
- Basic web UI (`07-web-ui-ux.md`): KB list, document manager, query/chat playground, access management screen. Skip wiki graph view and admin console screens for now.
- Since the upstream layer itself has zero auth, this phase is also where we lock down that nothing upstream-API-shaped is ever reachable except through our own authenticated `api`/`generator-api` — worth an explicit security check at the end of this phase (e.g. confirm sidecar processes bind to localhost/internal-only and are not reachable from outside the worker pod), not just an assumption.

**Exit criterion**: two separate orgs can each create KBs, upload documents, and query their own KBs through the UI, with no data leakage between orgs and correct role enforcement (a Viewer genuinely cannot add a document) — and an external network scan confirms no unauthenticated path to the upstream OpenKB layer exists.

## Phase 2 — MCP layer (the differentiator)

This is the phase that turns "a hosted OpenKB" into the actual product thesis from `00-overview.md`. Note this phase is simpler than originally scoped: there is no agent/machine identity concept to build (`02-data-model.md`, `03-auth-authn.md`), and the entire MCP tool surface is read-only from day one — there's no later "add write tools" phase to plan for, because that's a permanent property of this surface, not a staging decision (`04-authz-roles.md`).

- `kb_access` (already user-scoped from Phase 1, no extension needed), `api_tokens` with `read_only`/`kb_id` binding (`02-data-model.md`).
- `mcp-gateway` service (`05-mcp-integration.md`) implementing OAuth 2.1 + dynamic client registration as the only auth path — no static-key fallback to build or later deprecate, since every MCP token traces to one user's explicit consent from the start.
- Full read-only tool surface in one pass: `kb_query`, `kb_chat`, `kb_list_documents`, `kb_status`, `kb_search_entities` — there's no reason to stage these across phases the way an earlier write-inclusive design needed to, since none of them carry elevated risk relative to each other.
- "Connect an agent" UI flow (`07-web-ui-ux.md`'s Connections screen), including the consent screen stating access is read-only.

**Exit criterion**: Claude Code (or another MCP-capable agent) can connect to a specific KB's MCP endpoint, complete the OAuth consent flow as a real user, and get a grounded, cited answer to a real question, with the call showing up correctly in the audit log against that user's `actor_id` with `via='mcp'` — and an explicit verification that no MCP-reachable tool can add, remove, or edit anything, regardless of the connecting user's underlying KB role.

## Phase 3 — Audit polish, entity tooling, wiki browser

- `audit_log` fully wired across all services (every MCP call, every access grant change, every admin action) — this is also the phase to build the audit log UI screen and the org-wide MCP Connections admin screen (`07-web-ui-ux.md`).
- Wiki browser graph view (`07-web-ui-ux.md`) — the Obsidian-parity feature.
- Any remaining polish on the read-only MCP tool set from Phase 2 based on real usage (e.g. better entity search ranking) — there's no write-tool work queued here, unlike the earlier version of this roadmap; see "what changed" note below.

**Exit criterion**: an org admin can look at the audit log and answer "what has every MCP connection done against our KBs this week" without needing to query the database directly — and can independently confirm, just from the schema/permission model rather than from log inspection, that the answer to "could any of that have written something" is structurally no.

## Phase 4 — Admin, metering, and enterprise hardening

- `usage_ledger`, cost dashboards, soft alerts and hard caps (`08-admin-ops.md`).
- Full SSO (Entra ID primary, generic OIDC/SAML), `sso_enforced` org policy.
- Break-glass access flow (`04-authz-roles.md`).
- LLM provider BYO-key (`llm_provider_configs`, Key Vault integration) — org-level and per-KB override.
- Backup/versioning: per-KB Git versioning toggle, soft-delete-with-grace-period across orgs/KBs/documents.

**Exit criterion**: the product can pass a basic enterprise security review questionnaire — SSO, audit trail, data deletion/retention behavior, credential handling — without hand-waving any answer.

## Phase 5 — Scale & deployment flexibility

- Self-host-in-customer-tenant packaging (Bicep templates, per `09-deployment.md`).
- Collection-scoped `kb_access` grants fully exercised in UI (may already exist in the data model from Phase 1, but the UI/UX for it — `07-web-ui-ux.md`'s indented collection grouping — can land here if it wasn't prioritized earlier).
- Performance/cost tuning of `compiler-worker` scaling under real batch-upload volume.
- DR posture validation (`09-deployment.md`'s zone-redundant HA, GRS) under an actual SLA commitment.

## Explicitly deferred beyond this roadmap (not designed away, just not yet)

These are flagged in earlier documents as known future work, collected here so they don't get lost:

- **Group-based access grants** (assign role to a Team, not just individual users) — `04-authz-roles.md`, `02-data-model.md`.
- **Custom/configurable roles** beyond the fixed four — `04-authz-roles.md`.
- **Sub-document (paragraph/field-level) access control** — `04-authz-roles.md` flags this as a known limitation, addressed by document/collection splitting, not finer ACLs.
- **Multi-region active-active deployment** — `09-deployment.md`.
- **ML-based anomaly detection on MCP connection activity** — `08-admin-ops.md`; threshold-based flagging is the v1 approach.
- **Customer-facing status page** — `08-admin-ops.md`, build-vs-buy decision deferred.
- **Any write capability via MCP** — unlike the items above, this is not a "build it later" item but a deliberate permanent boundary; see `04-authz-roles.md` and `05-mcp-integration.md`. Listed here only so it isn't mistaken for an oversight if it comes up in planning.

## Sequencing principle

Notice that MCP (Phase 2) comes *before* full audit/admin polish (Phase 3–4). This is deliberate: the MCP integration is the product's actual reason to exist relative to "just self-host OpenKB and use Obsidian" — proving that works, even roughly, de-risks the product thesis earlier than polishing admin screens nobody's blocked on yet. Don't let Phase 1's UI completeness creep into a blocker for starting Phase 2.

## What changed: removal of the agent-identity model

An earlier version of this roadmap staged MCP work around a distinct `agent_identities` principal type, with read-only tools shipping first and write-capable tools (`kb_add_document`, `kb_generate_skill`) following in a later phase behind a Contributor+ grant. That entire model is gone. The product decision now is: an MCP connection always acts as the connecting human user, and the MCP surface is unconditionally read-only with no write tools, ever (`03-auth-authn.md`, `04-authz-roles.md`, `05-mcp-integration.md`). This simplified Phase 2 (no separate identity table or lifecycle to build) and eliminated what used to be Phase 3's write-tool work entirely — Phase 3 is now audit/UI polish only. If this boundary is ever revisited, treat it as a new product decision with its own threat model, not a resumption of the old staged plan.

## Note on tracking upstream

Phase 0's scope shrank materially because upstream OpenKB shipped an HTTP API layer (`init`/`add`/`query`/`list`/`status`) ahead of when this roadmap assumed we'd be building one ourselves (`01-architecture.md`). Treat this as the expected pattern, not a one-off: upstream is moving (the README's own roadmap lists a database-backed storage engine and a web UI as items they may build too), and this roadmap should be revisited whenever upstream adds something we'd otherwise have built — `remove`/`recompile`/`lint` over HTTP, native `chat`, Skill Factory over HTTP, or any auth primitive. Each of those, if/when they land upstream, should trigger a re-check of whether our equivalent in-progress or planned work (CLI-fallback paths in `compiler-worker`, our own `chat` session-assembly layer, etc.) should be replaced with a thin passthrough instead. Don't let sunk effort in a from-scratch implementation be a reason to ignore a simpler upstream option arriving mid-build. Note this applies only to the read-side: even if upstream someday adds authenticated write endpoints, our own MCP-is-read-only boundary (above) is a product decision independent of what upstream exposes, not a constraint we'd inherit or relax based on their auth model.

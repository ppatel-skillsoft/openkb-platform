# 08 — Administration & Operations

Covers what the platform needs operationally, beyond the screens already described in `07-web-ui-ux.md`'s admin console section. This is the "what does it take to run this responsibly for an enterprise customer" document.

## Usage metering & cost control

LLM compilation is genuinely expensive at scale — OpenKB's own description notes a single source document can touch 10–15 wiki pages during compilation, and `query`/`chat` calls add ongoing cost on top. This needs first-class tracking, not an afterthought.

- Every LLM call (compilation, query, chat, skill generation) writes to `usage_ledger` (`02-data-model.md`) with provider, model, input/output tokens, estimated cost, and the user who triggered it (plus `via`, distinguishing web/API from MCP).
- Cost estimation should use current provider pricing tables, kept up to date as a config (not hardcoded), since provider pricing changes over time.
- **Soft alerts**: configurable per-org or per-KB thresholds that notify admins (in-app + email) when usage crosses a percentage of a budget.
- **Hard caps**: optional, configurable per-KB or per-user, that block further LLM calls once a limit is hit — useful for `query`/`chat` since a retry loop on either the web/API or MCP side could otherwise run up cost with no one noticing in real time.
- Caps should fail gracefully: a blocked `kb_query` MCP call returns a clear error the connected agent can surface to its operator, not a silent timeout.

## Audit logging

Already specified at the data level in `02-data-model.md` and surfaced in the UI in `07-web-ui-ux.md`. Operational requirements:

- **Append-only, immutable.** No update/delete path in application code; if retention policy requires purging old entries, that's a separate, deliberate retention job, not part of normal app logic.
- **Minimum retention**: enterprise customers will commonly require 1 year minimum, often longer for regulated industries — make retention period a configurable org setting with a sensible default, not a hardcoded constant.
- **Export**: CSV/JSON export from the UI, and ideally a webhook/SIEM-forwarding option (many enterprise security teams want audit events streamed into Splunk/Sentinel/etc. rather than checked manually) — for Azure specifically, forwarding into Azure Monitor / Log Analytics is a natural integration to prioritize.
- **What must always be logged**: every access grant change, every SSO config change, every document add/remove, every MCP tool call, every manual wiki edit, every LLM provider config change, every break-glass access event (`04-authz-roles.md`).

## MCP connection monitoring

Distinct from generic audit logging because connection-level usage patterns matter differently than individual actions — an admin reviewing MCP activity is usually looking for *volume anomalies*, not, since the channel is read-only by construction, anything to do with scope creep or unauthorized writes (`04-authz-roles.md`):

- Per-connection view (one row per `oauth_mcp` token): call volume over time, which tools used, which KB, token cost trend — surfaced in the org-wide MCP Connections screen (`07-web-ui-ux.md`).
- Anomaly surfacing: a basic threshold-based flag (e.g. "this connection's call volume is 5x its 7-day average") is enough for v1 — don't build ML-based anomaly detection up front, it's not where early product value is.
- Stale credential surfacing: tokens unused for N days, flagged for the owning user and/or admin review/cleanup, reducing standing surface from forgotten integrations — even though a stale read-only token is lower-risk than a stale write-capable one would have been, it's still worth surfacing for hygiene.

## Backup, versioning, and recovery

- **Per-KB Git versioning** (toggle in KB settings, `07-web-ui-ux.md`): when enabled, every compilation/manual-edit commits to a Git history for that KB's wiki tree, giving diff and rollback essentially for free, consistent with OpenKB's existing plain-markdown-files design. This is cheaper to build than a custom revision system and gets the Obsidian-compatibility story (`00-overview.md`) for free too.
- **Database backups**: standard point-in-time recovery via Azure Database for PostgreSQL's built-in backup (see `09-deployment.md`) — no custom backup tooling needed.
- **Blob Storage**: soft-delete and versioning enabled at the storage-account level as a safety net beneath the application-level Git versioning.
- **Org/KB soft-delete with grace period**: deletions (`02-data-model.md`'s `deleted_at` pattern) go through a grace period (e.g. 30 days) before hard purge, with an admin-visible "recently deleted" view and restore action — standard enterprise expectation, easy to get wrong by skipping it.

## Self-host / data residency considerations

Flagged in `00-overview.md` as a requirement to plan for, not necessarily build first:

- Package the platform (control plane API, compiler workers, generator API, MCP gateway) as containers deployable into a customer's own Azure tenant (via Azure Marketplace managed application, or simple Helm/Bicep templates) for customers who require their data to never leave their own subscription.
- Keep all Azure-specific service bindings (Service Bus, Blob, Key Vault, Entra ID) behind interfaces, even though `09-deployment.md` commits to Azure as the only target initially — this is what makes a future self-host-in-customer-tenant story tractable without being a full re-architecture, since "self-host in Azure" is a much smaller lift than "self-host anywhere."
- LLM provider bring-your-own-key (already in the data model via `llm_provider_configs`) is part of the data-residency story too — a customer using their own Azure OpenAI deployment in their own region has a real answer to "does my document content leave my tenant."

## Support & operability

- **Health/status endpoints** for each service, feeding standard Azure Monitor / Application Insights dashboards.
- **Job queue visibility for admins**: a way to see "is compilation backed up right now" — even a simple admin-only queue-depth metric avoids a wave of "why hasn't my document finished compiling" support tickets during a load spike.
- **Customer-facing status page** once there's a SaaS tier with uptime expectations — not a v1 must-have, but worth deciding early whether it's built or bought (e.g. a hosted status-page tool) rather than designing it from scratch later.

## Compliance posture (groundwork, not full certification scope)

Not a substitute for actual compliance work, but architectural choices in this doc set that make later certification (SOC 2, ISO 27001, etc.) tractable rather than a rewrite:
- Audit log completeness and immutability (above) is a direct SOC 2 control area.
- Role separation and least-privilege defaults (`04-authz-roles.md`) map directly to common access-control controls.
- Credential handling via Key Vault references rather than DB-stored secrets (`02-data-model.md`, `09-deployment.md`) addresses a common audit finding before it happens.
- Data residency / self-host capability (above) is frequently a hard requirement, not a nice-to-have, for regulated-industry enterprise deals — worth treating as a roadmap priority rather than purely aspirational (see `10-roadmap-phasing.md`).

# 07 — Web UI & UX

OpenKB's own roadmap lists "Web UI for browsing and managing wikis" as a known gap. This is that surface, plus everything needed to make access control and MCP connections usable by non-CLI people.

## Information architecture

```
/                          → org switcher / KB list (if multiple orgs)
/orgs/{org}/kbs            → KB list for this org
/orgs/{org}/kbs/{kb}/
    overview               → KB home: stats, recent activity, quick query box
    documents               → document manager
    wiki                    → wiki browser (summaries/concepts/entities, graph view)
    query                   → query/chat playground
    connections             → MCP connection management (this user's own read-only agent connections)
    access                  → who has access to this KB, and at what role
    settings                → KB config, LLM provider override, danger zone (delete)
/orgs/{org}/admin/
    members                 → org member management
    mcp-connections          → org-wide view of every user's active MCP tokens
    sso                     → SSO configuration
    audit-log               → searchable audit trail
    usage                   → cost/usage dashboards
    llm-providers           → org-level LLM config
```

## Screen-by-screen

### KB Overview
First screen on entering a KB. Surfaces: document count, wiki page counts by type, last compilation time, a quick-query box (answers inline with citations, same component as the full playground), recent activity feed (last N audit events scoped to this KB). This is the "is my KB healthy and current" screen — should make compilation failures and stale documents visible immediately, not buried in a list.

### Document Manager
- Upload via drag-and-drop or URL paste (mirrors `openkb add <file_or_dir_or_URL>`), using the API's two-step signed-upload flow (`06-api-spec.md`). This screen, like all document write actions, is reached only through the authenticated web UI/control-plane API session — there is no MCP path for adding documents (`04-authz-roles.md`, `05-mcp-integration.md`), so "added by" is always a person, never something to attribute to a connected agent.
- Table view: filename, status (pending/compiling/complete/failed, with live status via websocket — don't make people refresh to see compilation finish), collection, added-by (the user who added it), token cost.
- Bulk actions: assign to collection, recompile, remove.
- Failed documents show the failure reason inline with a retry action, not just a red dot.
- Directory/batch upload should show aggregate progress (X of N compiled) rather than N separate progress bars cluttering the view.

### Wiki Browser
This is where OpenKB's existing markdown-wiki structure becomes genuinely browsable instead of "open it in Obsidian." Three views, switchable:
- **List view**: summaries/concepts/entities as a filterable, searchable table — fastest for "find the page about X."
- **Graph view**: wikilink relationships rendered as an interactive node graph (this is the thing Obsidian gives OpenKB users today for free — the web product should match that, not regress from it). Clicking a node opens the page; hovering previews it.
- **Page detail view**: rendered markdown, with a visible "contributed by" panel listing the source documents that touched this page (`wiki_page_documents` from the data model) — this is the traceability feature that makes the wiki trustworthy rather than a black box.

Manual edit is available here (Editor+, via the web UI only — not reachable via MCP) with a clear, persistent banner once a page has been manually edited: "This page has manual edits. Recompiling will overwrite them." — not a one-time toast that's easy to miss.

### Query / Chat Playground
The human-facing equivalent of the MCP `kb_query`/`kb_chat` tools (`05-mcp-integration.md`) — letting a person test exactly what a connected agent would get back, citations included, before they rely on it. Toggle between single-question mode and multi-turn chat mode. Citations render as clickable chips that jump to the relevant wiki page, not just a footnote list. Session history (past chats) listed in a sidebar, resumable — mirrors `openkb chat --resume`. A chat session started here and one started via MCP are both just sessions owned by this user (`02-data-model.md`'s `via` field distinguishes them for display, e.g. a small icon showing where a session originated), and both are resumable from either surface.

### Connections (the MCP UX — core differentiator surface)
This screen is the product's signature feature and should be treated with proportionate design attention. It is scoped to **the current user's own connections** — there's no separate identity to manage here, just this person's read-only links between their account and their agents.
- **"Connect an agent" button** kicks off the OAuth consent flow described in `03-auth-authn.md`/`05-mcp-integration.md` for agents that support dynamic registration (Claude, Claude Code, Claude Desktop) — show recognizable client icons/names where the OAuth client metadata supports it, so a user sees "Claude Code wants to connect" rather than an opaque client id. The consent copy states plainly that the resulting access is **read-only** — there's no role/scope picker to show, since there's nothing to choose.
- **Manual setup panel**: for agents/configs that need the raw MCP endpoint URL and a way to complete the OAuth flow non-interactively (e.g. a headless agent), show copy-pasteable instructions per common client (`03-auth-authn.md`'s "headless agents" flow).
- **My connections list**: each row shows a user-supplied label (e.g. "Claude Code — laptop"), which KB it's scoped to, last used, expiry if set, and a revoke action. Every row is, structurally, just this user's own access — read-only, single-KB — so there's nothing to visually distinguish by "type" the way an earlier design needed; the only thing worth flagging is staleness (unused for N days).
- **Activity tab** (or link out to the audit log filtered to this KB + `via=mcp`): recent MCP calls made through this user's connections, so they (or, with the right role, a KB Owner looking at the broader access screen) can see "what has actually been asked through this connection."

### Access Management
Single table: every user with access to this KB, their role, whether it's KB-wide or collection-scoped, who granted it, expiry. Add-access flow lets you search org members and grant a role + optional collection scope + optional expiry — directly reflects `kb_access` (`02-data-model.md`). Collection-scoped grants visually grouped/indented under their collection rather than flattened into one undifferentiated list, since "who can see what" is exactly the question this screen needs to answer at a glance. Worth a small explanatory note near the role selector here, since it's a common point of confusion: *any* role shown here governs web/API access only — connecting an MCP agent never exceeds read, regardless of which role a user holds (`04-authz-roles.md`). Don't let users think granting Owner "to be safe" changes what an agent can do.

### KB Settings
Name/description, compilation config (language, PageIndex threshold, entity types, extra headers — mirrors OpenKB's `config.yaml`), LLM provider override (defaults to org config, can be overridden per-KB), Git versioning toggle, danger zone (archive/delete) clearly visually separated and requiring typed confirmation for delete.

## Admin console screens

### Members
Standard invite/role-management table at the org level (`org_role`, not KB roles — link out to per-KB access screens rather than trying to show KB-level grants here, which would get unwieldy fast for an org with many KBs).

### MCP Connections (org-wide)
Every active `oauth_mcp` token across every user in the org, with the owning user, which KB it's scoped to, last used, and a revoke action — this is the screen that answers "what external agent access exists in our org right now," useful for security review and offboarding independent of any single KB's Connections tab. Since every row is read-only by construction, this view is about visibility and cleanup (stale connections, departing employees), not about catching anything writing where it shouldn't — that's structurally impossible, not just monitored for.

### SSO Configuration
Provider selection, metadata/client config entry, test-connection action before enforcing, and the `sso_enforced` toggle clearly explained ("members will no longer be able to log in with a password") with a confirmation step.

### Audit Log
Filterable (date range, KB, user, `via` (web/api/mcp/system), action type), exportable (CSV/JSON) for compliance review. Default view should bias toward recency and toward write/access-change events over routine query traffic, with a clear filter to drill into MCP query activity specifically when needed — since every MCP entry is read-only, this filter is for visibility/usage understanding, not threat-hunting for unauthorized writes.

### Usage Dashboard
Cost over time, broken down by KB and by user, with the ability to set soft alerts and hard caps — directly surfaces `usage_ledger` (`02-data-model.md`). This screen matters more than it might initially seem: LLM compilation cost was flagged in `00-overview.md` as something that can surprise people, and it's the kind of thing that erodes trust in the product if it's opaque.

### LLM Providers
Org-default provider/model/credential, with per-KB overrides visible/linkable from here. Credential entry writes straight to Key Vault via the API (`06-api-spec.md`) — never displays a previously-entered key back, only a masked reference and a "replace" action.

## Cross-cutting UX principles

- **MCP-originated activity is labeled, not flagged.** A small, consistent indicator (icon or tag) next to anything that happened `via=mcp` is useful for understanding usage patterns, but it should read as informational, not as a warning — there's no elevated risk to call out, since the channel is read-only by construction.
- **Async operations show real status, not a spinner that lies.** Compilation and recompilation are backgrounded jobs (`01-architecture.md`); the UI should reflect actual job state via websocket/poll, including failure states with actionable detail.
- **Citations are clickable everywhere they appear** — query playground, chat, and any MCP-originated chat session viewed after the fact. This is the single UX thread that ties back to the product's core trust proposition from `00-overview.md`.
- **Permission-denied states explain why, not just block.** If a Viewer can't see the Access Management tab, say "Ask a KB Owner for access to manage this" rather than hiding the nav item with no explanation — this matters more in an enterprise context where the person hitting the wall often isn't the person who can fix it, and needs to know who to ask.

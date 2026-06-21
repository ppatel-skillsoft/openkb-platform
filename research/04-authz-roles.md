# 04 — Authorization & Roles

Pairs with `03-auth-authn.md`. That document establishes *who* is making a request and how MCP tokens are issued; this one establishes *what they're allowed to do*. Backed by `kb_access` and `org_members` in `02-data-model.md`.

## Two independent axes

1. **Org-level role** — governs administration of the organization itself (billing, SSO config, creating KBs, managing members). Lives in `org_members.org_role`.
2. **KB-level role** — governs what a user can do on *one specific knowledge base*. Lives in `kb_access.role`. A user can be a KB Owner on one KB and have no access at all to another KB in the same org — org membership does not imply KB access.

This separation matters because in a real enterprise, "I work at this company" does not mean "I should be able to read every knowledge base the company has." HR's KB and Engineering's KB are both inside one org; access should not leak between them by default.

## A third axis: channel (web/API vs. MCP) caps what a role can do

This is the important addition on top of the usual role-permission story, and it's the core rule of this whole document: **regardless of a user's KB-level role, anything reached via an MCP connection is read-only.** Role (`viewer`/`contributor`/`editor`/`owner`) governs what a user can do through the web UI and the authenticated control-plane API. MCP is a strictly narrower lens onto that same role — it can never see more than Viewer-equivalent capability, no matter how privileged the user actually is.

Concretely: a KB Owner who connects Claude Code to their KB via MCP gets exactly the same tool access as a Viewer would — `query` and `list`/`status` style read tools — never `add_document`, never anything that writes. To add a document, that same Owner uses the web UI or the control-plane API, authenticated as themselves through a normal session, not through the MCP token.

### Why this is a hard rule, not a default

Agents are good at taking actions quickly and at volume, and an enterprise KB is exactly the kind of shared, cross-team resource where an unintended or misinterpreted write (a bad document added, an existing one removed) is expensive to notice and unwind, especially across many KBs or many agents. Keeping every MCP-reachable action strictly read-only removes that failure mode by construction rather than by relying on prompting, scoping discipline at issuance time, or per-grant configuration that someone could get wrong. It also makes the product's safety story simple to state to a security reviewer: *nothing reachable through an external agent integration can modify your knowledge base, period* — not "writes require Contributor+ and a separate consent step," which is a weaker and harder-to-audit claim.

## Org-level roles

| Role | Can do |
|---|---|
| **Owner** | Everything Admin can, plus: billing, deleting the org, transferring ownership, changing SSO enforcement |
| **Admin** | Manage members (invite/remove/change org_role), create/archive KBs, configure SSO, view org-wide audit log, manage org-level LLM provider config |
| **Member** | Use KBs they've been granted access to via `kb_access`; can create new KBs (becomes KB Owner of those) unless org policy restricts KB creation to Admins |
| **Billing** | Billing/invoices only; no content or admin access — exists so finance can be added without giving them KB visibility |

A org should always have at least one Owner; deleting the last Owner is blocked at the application layer (not just a UI nicety — enforce server-side).

## KB-level roles

Applied via `kb_access`, optionally scoped to a `collection_id` within the KB rather than the whole KB. **These columns describe web UI / control-plane API capability.** The MCP column is intentionally identical across every row, because it doesn't vary by role — see above.

| Role | Documents (web/API) | Wiki pages (web/API) | Access mgmt | Config | Via MCP |
|---|---|---|---|---|---|
| **Owner** | add/remove/recompile | edit directly | grant/revoke access, delete KB | change LLM/compilation config | query/read only |
| **Editor** | add/remove/recompile | edit directly | — | — | query/read only |
| **Contributor** | add (not remove) | — | — | — | query/read only |
| **Viewer** | — | read only | — | — | query/read only |

Notes:
- "Edit wiki pages directly" (Owner/Editor) means manual edits to compiled markdown — useful for human correction of LLM output. This is distinct from triggering a recompile; OpenKB's `recompile` overwrites manual edits, so the UI must warn clearly before recompiling a KB that has manual edits (see `07-web-ui-ux.md`).
- There is deliberately **no role above Owner at the KB level** — org Admins/Owners do not get implicit KB access. If an org Admin needs into a specific KB, they get an explicit `kb_access` grant like anyone else. (Exception: for legal/compliance break-glass access, see "Break-glass access" below.)
- The "Via MCP" column being uniformly "query/read only" is not a simplification of the table — it's the literal permission outcome. Don't read it as shorthand for "roughly read-only with some role-based variation"; there is none.

## Permission matrix (action × channel)

| Action | Web UI / API, by role | Via MCP |
|---|---|---|
| Query / chat | Viewer+ | ✅ always (any role Viewer+) |
| List documents/entities | Viewer+ | ✅ always |
| Add document | Contributor+ | ❌ never |
| Remove document | Editor+ | ❌ never |
| Trigger recompile | Editor+ | ❌ never |
| Manually edit wiki page | Editor+ | ❌ never |
| Generate skill (Skill Factory) | Contributor+ | ❌ never |
| Manage `kb_access` grants | Owner | ❌ never |
| Change KB config | Owner | ❌ never |
| Delete KB | Owner | ❌ never |
| Connect/manage own MCP tokens | any role with KB access | n/a — this action itself is web/API only |

This table is the literal source for the policy engine's static rule set — implement it as data (a seed table or config, not a hardcoded switch statement), so a future custom-role feature doesn't require rewriting the check logic, only adding rows. The MCP column should be implemented as an explicit, separate gate (e.g. "is this token `read_only`? if so, only permit actions flagged `mcp_allowed`") rather than folded into the same role-lookup path as the web/API column — keeping it a structurally separate check is what makes "MCP can never write" hold even if the role-based matrix above grows more rows later.

## Collections as the sub-KB grain

A `kb_access` row with a non-null `collection_id` grants the role *only within that collection*. A user can hold different roles on different collections of the same KB (e.g. Viewer on the whole KB, Editor on one specific collection they own content for). Resolution rule: **most specific grant wins**; if a user has both a KB-wide grant and a collection-scoped grant, the collection-scoped grant governs actions within that collection, and the KB-wide grant governs everything else.

This is the mechanism for the "HR docs vs general docs in one KB" scenario from `00-overview.md` — rather than forcing a split into multiple KBs (which would fragment the wiki's cross-referencing, undermining OpenKB's core value), sensitive material goes in its own collection with a tighter grant list. The same MCP-is-always-read-only rule applies per collection too: an Editor on a sensitive collection still can't write to it via MCP, only via the web UI/API.

What this does **not** do: per-paragraph or per-field redaction within a single page. If content within one document needs to be split-access at a sub-document level, it needs to be split into separate source documents assigned to different collections — flag this as a known limitation, not a TODO to silently solve later (see `02-data-model.md`'s "deliberately not in v1").

## Break-glass access

For legal hold, security incident response, or compliance audit, an org Owner should be able to grant themselves temporary access to any KB in the org — but this must be **loud, not silent**:
- Requires explicit action (not implicit from org_role)
- Creates a `kb_access` grant with `expires_at` forced to a short window (e.g. 24h, configurable)
- Generates a high-severity audit log event visible to all org Admins, not just logged quietly
- KB Owners of the affected KB get notified (in-app, and email if configured)
- Like every other grant, break-glass access is still subject to the MCP-is-read-only rule if exercised through an MCP connection rather than the UI.

## Policy engine contract

Whatever implements the actual check (library inside `api`/`generator-api`/`mcp-gateway`, per `01-architecture.md`) should expose two related but distinct functions, conceptually:

```
can(user_id, action, resource) -> bool
  // role-based check against kb_access — used by web UI and control-plane API
  resource: {type: 'kb'|'collection'|'org', id}

can_via_mcp(user_id, action, resource) -> bool
  // = can(user_id, action, resource) AND action is in the MCP-allowed read set
  // i.e. role-sufficiency is necessary but never sufficient on the MCP path
```

Resolution order for `can`: org-level checks (is the org active, is this subject even a member) → most-specific `kb_access` grant (collection-scoped beats KB-wide) → static permission matrix for that role × action. No action should be granted by falling through to a default-allow; the policy engine fails closed. `can_via_mcp` always additionally requires the action to be in the fixed, small set of MCP-allowed actions (query, chat, list, status, entity search) — this set is not derived from role at all, it's a constant, and should be implemented as one, not as a per-role lookup that happens to currently evaluate the same way for every role.

## What's deferred, not designed away

- **Custom/configurable roles** (beyond the fixed four) — likely a v2 enterprise-tier feature once real usage shows where the fixed roles pinch. Don't build a generic role-builder UI for v1.
- **Group-based grants** (assign a role to a Team rather than per-user) — flagged in `02-data-model.md` as a clear v2 schema addition (`groups` table + `kb_access` gaining a group-subject option). Don't retrofit this into v1's grant model speculatively.
- **Any write capability via MCP** — explicitly out of scope, not just unscheduled. If this is ever revisited, treat it as a new, carefully-considered product decision requiring its own threat model, not an incremental loosening of `read_only` on the existing token type.

# 03 — Authentication

This document covers *who is making a request and how we know that's true*. Authorization (*what they're allowed to do*) is `04-authz-roles.md`. They're a deliberate pair — read both before implementing anything access-control-related.

## One principal type: there is no separate agent identity

There is exactly one kind of principal in this system: a **user**. A human logs in and uses the web UI as themselves. An AI agent connecting via MCP (Claude, Claude Code, an internal bot) also acts **as that same user** — using a token tied to their account, constrained to read-only — not as some separate machine identity with its own permission surface. This was an earlier design direction (a distinct `agent_identities` principal type, mirrored throughout `02-data-model.md`) and it has been deliberately replaced with this simpler model. Two product decisions make this safe:

1. **MCP-issued tokens are always read-only, with no exception.** An agent can query and read a KB through MCP; it can never add, remove, edit, or recompile anything, no matter what role the underlying user holds on that KB — even a KB Owner's MCP token cannot write. Write operations exist only through the web UI and the authenticated control-plane API, both of which are human-driven, session-based flows. See `04-authz-roles.md` for the full reasoning.
2. **No new permission is created by connecting an agent.** An MCP token is scoped to exactly one KB and inherits whatever that user could already see there — connecting Claude Code to a KB never grants access the user didn't already have, and never grants anything beyond read.

This removes a whole category of design surface the earlier two-principal model required (agent identity lifecycle, agent-specific revocation flows, agent-vs-human visual distinction throughout the UI, scope-immutability rules for a second principal type) without losing the actual product capability — "let an agent answer questions from our KB" — since that was always meant to be read-only in practice anyway.

## Human authentication

### Primary path: Microsoft Entra ID (SSO)
Since this is Azure-targeted, Entra ID is the first-class SSO integration, via standard OIDC (authorization code + PKCE flow). An org admin configures this once (`sso_config` table); after that, org members authenticate via their corporate identity, and org-level group/role claims from Entra ID can optionally be mapped to `org_role` on first login (configurable, off by default — don't auto-grant admin from an IdP claim without explicit org admin opt-in).

Also support generic OIDC and SAML for orgs on Okta, Google Workspace, or other IdPs — don't hard-couple the SSO implementation to Entra ID specifically even though it's the priority. Use a standard library (e.g. an OIDC/SAML broker) rather than hand-rolling protocol handling.

### Fallback path: email + password / magic link
For trial users, small teams, or orgs not yet ready to wire up SSO. Standard practice: bcrypt/argon2 password hashing, email verification on signup, rate-limited login attempts, optional TOTP-based MFA. Once an org sets `sso_enforced = true`, password login is disabled for that org's members (existing sessions get a grace period, not an instant kill, to avoid support tickets at rollout).

### Session handling
Standard web session via short-lived JWT + refresh token, refresh token rotated on use, stored as httpOnly/secure/sameSite cookie for the web UI. Nothing unusual here — this is a normal SaaS session model, don't over-engineer it.

## MCP / agent authentication

This is still the part that needs the most care, even with the simplified one-principal model — the question isn't "whose identity is this" anymore (it's always the user's), it's "how does a user safely hand a long-lived, read-only credential to an agent that may run unattended."

### MCP authentication flow (OAuth, primary and only path)
MCP's modern auth model is OAuth 2.1 with the MCP server acting as an OAuth-protected resource server. Brief for the build agent:

1. Agent (e.g. Claude, Claude Code) attempts to connect to `https://api.yourapp.com/mcp/{kb_id}`.
2. `mcp-gateway` returns a 401 with `WWW-Authenticate` pointing to the authorization server metadata, per the MCP authorization spec.
3. The user is redirected through a real OAuth consent screen on our platform — they log in (as themselves, via the human auth path above) if not already, see "Claude Code is requesting **read-only** access to KB Y," and approve.
4. On approval, an `api_tokens` row is created, tied to `user_id` = the logged-in user, `kb_id` = the specific KB, `read_only = true` (enforced server-side at issuance — not a flag the client can request away from), `issued_via = 'oauth_mcp'`.
5. The agent uses the access token as a bearer token on subsequent MCP calls; `mcp-gateway` validates it, resolves it to the user, and checks that user's `kb_access` role on that KB via the policy engine — same check as if the user had made the call themselves through the UI, with the additional, separate constraint that only read tools are ever reachable through an `oauth_mcp` token regardless of role (`04-authz-roles.md`).

This consent-screen step is the actual "connect an agent" UX moment in the product — see `07-web-ui-ux.md`'s Connections panel. It should feel like authorizing a third-party app (the OAuth flows people already know from Google/Slack/etc.), and the copy should say "read-only" explicitly, not just imply it.

### Headless / non-interactive agents
A server-side cron job or deployed bot that can't do an interactive browser redirect still goes through the same OAuth flow at setup time — a human runs the authorization step once (e.g. from their own browser, pointing the resulting token at the headless agent's config), and the resulting long-lived (but still read-only, still revocable, still expirable) token is what the headless agent uses afterward. This is the same pattern as, for example, authorizing a CI bot to post to Slack: a human authorizes once, the bot holds the resulting token. There is no separate "static API key issued directly to a machine with no human consent step" path — every token traces back to one explicit OAuth grant by one named user.

### Token properties
- **MCP tokens are always read-only** (`api_tokens.read_only = true`, `02-data-model.md`) — this is enforced at the API/MCP-gateway layer on every call, not just at issuance, so a bug in the issuance flow can't silently produce a writable token.
- **Scoped to one KB.** An `oauth_mcp` token is never KB-wide-across-the-org or org-wide; the consent screen names the specific KB, and the token is unusable against any other KB.
- **Revocable independently of the user's session.** A user can revoke a specific MCP connection (delete the `api_tokens` row) from the Connections panel without logging out of the web UI elsewhere — these are independent credentials, not the same session token.
- **Every token use updates `last_used_at`**, surfaced in the UI so users/admins can spot stale, forgotten connections to clean up.
- **Manual PATs** (`issued_via = 'manual_pat'`) remain available as a separate, explicit self-service feature for programmatic API use outside MCP (e.g. scripting against the control-plane API) — these can be scoped more broadly than `oauth_mcp` tokens at the issuing user's own discretion, since they're a different feature with a different (developer/scripting) audience, not the MCP path.

### Offboarding and revocation
- Revoking a user (org removes them) immediately invalidates all of that user's tokens, including every MCP connection they'd authorized — there's no separate "agent identity" to consider, which was exactly the awkward case the earlier model needed to handle explicitly and this model doesn't.
- KB deletion cascades to revoke all `kb_access` grants and any `oauth_mcp` tokens scoped to that KB.
- Admins can see, from the org-wide Agent Connections view (`07-web-ui-ux.md`), every active `oauth_mcp` token across the org's users, and can revoke any of them directly — useful for offboarding or incident response without needing to revoke the user's entire account.

## What we explicitly do not do

- No machine/agent identity table, no agent-specific OAuth client registry beyond what's needed for standard MCP dynamic client registration, no agent-specific role.
- No write-capable MCP tokens, ever — not even for KB Owners, not even with an extra confirmation step. If a future product need genuinely requires agent-driven writes, that's a distinct, deliberately-scoped future decision (see `10-roadmap-phasing.md`'s deferred list), not a default extension of this token type.
- No silent scope escalation — connecting an agent never grants access beyond what the authorizing user already has, and never beyond read regardless of what they have.

# 00 — Overview & Product Brief

## Purpose of this document set

This is the planning and build reference for **OpenKB Enterprise** (working name) — a multi-tenant, enterprise-grade product built on top of the open-source [OpenKB](https://github.com/VectifyAI/OpenKB) wiki-compilation engine. It is written to be handed directly to a build agent (or a human team) as the source of truth for architecture, data model, auth, roles, MCP integration, API surface, UI, administration, and deployment.

Read this file first. Each other file in this set goes deep on one concern:

| File | Covers |
|---|---|
| `01-architecture.md` | System architecture, services, how OpenKB's pipeline is wrapped |
| `02-data-model.md` | Postgres schema, entities, relationships |
| `03-auth-authn.md` | Identity, login, SSO, agent/machine credentials |
| `04-authz-roles.md` | Roles, permissions, policy model, scoping |
| `05-mcp-integration.md` | MCP server design, tools, OAuth, per-KB endpoints |
| `06-api-spec.md` | REST API surface (control plane) |
| `07-web-ui-ux.md` | Web UI information architecture, screens, flows |
| `08-admin-ops.md` | Admin console, audit, metering, usage cost |
| `09-deployment.md` | Azure-specific deployment architecture |
| `10-roadmap-phasing.md` | Build order, milestones, what's deferred |

## What we're building, in one paragraph

OpenKB (open source) is a single-user system that compiles raw documents into a structured markdown wiki — summaries, concept pages, entity pages, cross-links — using an LLM, with PageIndex for long-document retrieval and no vector DB. It originally shipped as CLI-only; an upstream branch (`001-fastapi-http-api`) has since added an HTTP layer covering `init`/`add`/`query`/`list`/`status`, but it remains single-tenant and has no authentication (see `01-architecture.md`). It still has no multi-tenancy, no auth, no web UI, no `chat`, and no MCP server (only a read-only agent *skill* file). **OpenKB Enterprise** wraps that compilation engine — using the upstream HTTP layer where it exists, and CLI/our-own-build where it doesn't — in a multi-tenant service: organizations create knowledge bases, control who (and which AI agents) can read, write, or administer them, and connect any MCP-capable agent (Claude, Claude Code, internal bots) to a given KB through a properly authenticated, scoped, audited MCP endpoint.

## What we are explicitly NOT rebuilding

The wiki compilation pipeline itself — markitdown for short docs, PageIndex tree indexing for long PDFs, the LLM-driven summary/concept/entity generation, the `wiki/AGENTS.md` schema-as-instructions pattern — is good, working design. We wrap it, queue it, multi-tenant it, and put access control around it. We do not redesign how knowledge compiles. Treat the compilation engine as a library/worker we call, not a thing we rewrite. As of the `001-fastapi-http-api` upstream branch, this extends to a thin slice of HTTP transport too (`init`/`add`/`query`/`list`/`status`) — we don't write a first HTTP wrapper for those operations, we integrate with the one that exists. Full detail in `01-architecture.md`.

## Core product principles

1. **The KB is the tenancy and security boundary.** Every knowledge base belongs to exactly one organization, has its own storage, its own access list, and its own MCP endpoint. There is no "org-wide MCP firehose" by default.
2. **Agents are not users.** A machine identity connecting via MCP is a distinct principal type from a human login, with its own credential lifecycle, its own default-to-read-only posture, and its own audit trail. Never silently inherit a human's full permission set.
3. **Citations are the trust feature.** OpenKB's `query` already returns grounded answers with citations back to source documents. Every layer we add (MCP tool, API, UI) must preserve and surface that traceability — it's the main reason an enterprise would trust agent-generated answers over a black box.
4. **Policy as data, not code.** Permissions live in a database table (subject × resource × action), not in scattered `if user.role == 'admin'` checks, so adding a role or resource type later doesn't require a code change in twelve places.
5. **Self-host-capable from day one.** Enterprise buyers in regulated industries will ask "can this run in our tenant." Architecture decisions (this doc set assumes Azure) should not assume a SaaS-only world even if SaaS is the first GA target.

## Target deployment

This document set assumes **Azure** as the primary cloud target (Entra ID for identity, Azure Database for PostgreSQL, Blob Storage, Service Bus, AKS or Container Apps for compute). See `09-deployment.md` for specifics. The architecture in `01-architecture.md` is written so that swapping Azure-specific services for AWS/GCP equivalents later is a configuration change, not a redesign — but we are not building that abstraction layer up front; we are building for Azure.

## Glossary

- **KB (Knowledge Base)**: a single compiled wiki — the unit of tenancy, access control, and MCP exposure.
- **Org (Organization)**: the billing and admin boundary; owns one or more KBs and has member users.
- **Agent identity**: a machine principal (representing an AI agent, e.g. a Claude Code session or a deployed bot) with its own scoped credentials, distinct from a human user.
- **Compilation**: the process of turning a raw document into wiki pages (summary, concepts touched/updated, entities touched/updated).
- **Generator**: an OpenKB concept — something that reads the compiled wiki and produces output (query, chat, Skill Factory). We expose generators as both API endpoints and MCP tools.
- **Collection**: a sub-grouping of documents within a KB, used for finer-grained access control than "all or nothing" at the KB level.

## How to use this doc set if you are a build agent

Read `00` and `01` fully before writing any code. Read `02` before creating migrations. Read `03`/`04` together before implementing any endpoint that touches access control — they are designed as a pair. Read `05` before building anything MCP-related; it depends on `03`/`04` being in place conceptually even if not fully implemented. `10-roadmap-phasing.md` tells you the order to actually build things in — it deliberately does not match the numbering of this file set, because reading order and build order are different.

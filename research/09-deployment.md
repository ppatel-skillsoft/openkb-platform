# 09 — Deployment (Azure)

This document set targets **Azure** as the deployment platform, per product decision. This file maps the logical services from `01-architecture.md` onto concrete Azure resources.

## Service-to-Azure mapping

| Logical component | Azure service | Notes |
|---|---|---|
| `api` (control plane) | Azure Container Apps (or AKS if org already standardized on it) | Stateless, horizontally scaled, autoscale on HTTP concurrency |
| `compiler-worker` | Azure Container Apps jobs / KEDA-scaled deployment | Scales on Service Bus queue depth |
| `generator-api` | Azure Container Apps | Separate scaling profile from compiler-worker per `01-architecture.md`'s separation rationale |
| `mcp-gateway` | Azure Container Apps | Public-facing; fronted by Azure Front Door / App Gateway |
| Job queue | Azure Service Bus (queues, possibly topics if event fan-out grows) | |
| Metadata DB | Azure Database for PostgreSQL — Flexible Server | Private endpoint, no public access |
| Object storage | Azure Blob Storage | Per-KB container or prefix, per `01-architecture.md` |
| Cache / session scratch | Azure Cache for Redis | For active chat session scratch state if Postgres-only proves insufficient (`01-architecture.md`'s open question) |
| Secrets | Azure Key Vault | All LLM provider credentials, SSO client secrets — referenced by id from Postgres, never stored raw (`02-data-model.md`) |
| Human identity | Microsoft Entra ID | Primary SSO integration (`03-auth-authn.md`); also used for the platform's own internal/admin auth if desired |
| Logging/monitoring | Azure Monitor + Application Insights + Log Analytics | Audit log SIEM-forwarding target (`08-admin-ops.md`) |
| CDN/edge for web UI | Azure Front Door + Static Web Apps (or Container Apps if SSR) | |
| Container registry | Azure Container Registry | |

## Network architecture

```
                         Internet
                            │
                  Azure Front Door (WAF, TLS termination)
                            │
              ┌─────────────┴─────────────┐
              │                           │
        Static Web App               Container Apps Environment
        (web UI)                     (VNet-integrated)
                                            │
                          ┌─────────────────┼─────────────────┐
                          │                 │                 │
                         api          generator-api      mcp-gateway
                          │                 │                 │
                          └────────┬────────┴────────┬────────┘
                                   │                 │
                          Private Endpoint     Private Endpoint
                                   │                 │
                          PostgreSQL Flexible    Blob Storage
                          Server (private)        (private)
                                   │
                              Service Bus
                              (compiler-worker
                               consumes here)
                                   │
                            compiler-worker
                            (VNet-integrated,
                             no public ingress)
```

Key points for the build agent:
- All data-plane services (`api`, `generator-api`, `mcp-gateway`, `compiler-worker`) live inside a Container Apps Environment attached to a VNet; **only `mcp-gateway` and `api` have public ingress** (through Front Door), `compiler-worker` has none, `generator-api` is reachable only from `mcp-gateway`/`api` internally.
- PostgreSQL and Blob Storage are reached via **private endpoints only** — no public network access on the data tier, full stop. This is a default enterprise security expectation, not a hardening pass to do later.
- Key Vault accessed via **managed identity** from each Container App — no credentials in environment variables or config files, ever.

## Identity for service-to-service auth

Use **Azure Managed Identities** for all service-to-service and service-to-resource auth (Container App → Key Vault, Container App → Service Bus, Container App → Blob) rather than connection strings/keys where Azure supports it. This eliminates an entire class of credential-leak risk and is the idiomatic Azure pattern — don't reach for static connection strings out of familiarity when managed identity is available.

## Multi-region / DR posture

Single-region deployment for initial GA (per `01-architecture.md`'s deferred-questions list), with:
- PostgreSQL Flexible Server's built-in zone-redundant HA configuration within the primary region from day one (this is a checkbox, not a project — enable it).
- Geo-redundant storage (GRS) on the Blob Storage account for the wiki/raw content, so a region-level outage doesn't risk data loss even before full multi-region compute is built.
- A documented (not necessarily automated) region-failover runbook for the database and compute tier, revisited once there's a customer commitment (SLA in a contract) that requires it — don't build active-active multi-region speculatively.

## Environments

Three standard tiers: `dev`, `staging`, `production`, each a fully separate set of the above resources (separate resource groups, separate Postgres instances, separate Service Bus namespaces) — no shared infrastructure between environments, including for the self-host story below, since customers evaluating the product will often want to see a clean staging→production promotion path documented.

## Self-host-in-customer-tenant path

Per `08-admin-ops.md`'s data residency note: package as a Bicep/Terraform template (Bicep is the more natural choice given the Azure-first target) that stands up the same architecture inside a customer's own subscription, using their own Entra ID tenant for SSO and optionally their own Azure OpenAI deployment for the LLM provider. This is meaningfully easier than a cloud-agnostic self-host story specifically because the architecture is already Azure-native end to end — there's no abstraction layer to maintain, just a parameterized deployment template. Treat this as a packaging/ops exercise once the SaaS product is stable, not a parallel architecture (`10-roadmap-phasing.md`).

## CI/CD

- GitHub Actions (consistent with OpenKB's own existing `.github/workflows` in the upstream repo) building container images, pushing to Azure Container Registry, deploying via `az containerapp update` or a Bicep-driven pipeline.
- Database migrations run as a pre-deploy step (standard migration tool — e.g. Alembic if the backend is Python, consistent with OpenKB's existing Python codebase) gated behind a manual approval for production.
- Separate deploy pipelines per service so `compiler-worker` can ship independently of `api`/`mcp-gateway` — they have different release cadences in practice (the compilation engine changes when OpenKB's core logic changes; the API/gateway change with product features).

## Cost considerations specific to Azure

- Container Apps' consumption plan is a reasonable default for `api`/`generator-api`/`mcp-gateway` given bursty traffic; `compiler-worker` may be more cost-predictable on a dedicated plan if compilation volume is steady, but start with consumption and revisit once real usage patterns exist — don't over-provision ahead of data.
- Azure OpenAI (if used as the default/platform LLM provider rather than purely BYO-key) should be provisioned with deployment-level rate limits matching the platform's own quota system (`08-admin-ops.md`) so the two don't fight each other.

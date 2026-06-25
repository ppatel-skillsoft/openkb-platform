<!--
SYNC IMPACT REPORT
==================
Version change: 1.1.0 → 2.0.0 (MAJOR — complete rework: new product positioning, eight new or
  significantly redefined principles, enterprise compliance section, platform architecture
  section, documentation & style standards, and Git Flow governance)

Modified principles:
  - "Layered Architecture" retained and deepened with sidecar subprocess pattern
  - "CLI-First, API-Consistent" → subsumed into "Repository Architecture" section
  - "Async by Default for I/O" — retained, expanded
  - "Test Coverage is Non-Negotiable" → renamed "Test Discipline"; ruff/bandit gates added
  - "Supply-Chain Discipline" — retained, openkb-core pinning rule added
  - "Robustness and Graceful Degradation" — retained, multi-tenant context added

Added sections:
  - Product Positioning (deployment models, Azure cloud, region selection)
  - Principle I:  Local-First Development (new)
  - Principle II: Security at Every Layer (new)
  - Principle III: Observability (new)
  - Principle IV: Per-Customer Isolation (new)
  - Principle V:  Enterprise Compliance Posture (new)
  - Principle VI: Configurability (new)
  - Repository Architecture (generator_api, compiler_worker, openkb-core sidecar)
  - Documentation & Style Standards (new)

Removed sections: none (all v1.1.0 content merged or superseded)

Templates requiring updates:
  - .specify/templates/plan-template.md ✅ updated — Constitution Check expanded;
      language/platform defaults updated for openkb-platform
  - .specify/templates/spec-template.md ✅ updated — security, observability, isolation
      acceptance criteria guidance added
  - .specify/templates/tasks-template.md ✅ updated — Phase 2 foundational tasks now
      reference ruff, bandit, logging, and per-customer isolation scaffolding

Deferred TODOs: none
-->

# openkb-platform Constitution

**Version**: 2.0.0 | **Ratified**: 2026-06-19 | **Last Amended**: 2026-06-25

---

## Product Positioning

openkb-platform is an enterprise knowledge-base platform delivered in three deployment models:

| Model | Control Plane | Data Plane | Primary Use |
|-------|--------------|------------|-------------|
| **Hosted (SaaS)** | Our cloud (Azure) | Our cloud (Azure) | Rapid evaluation; default entry point |
| **Hybrid** | Our cloud (Azure) | Customer cloud (Azure Blob, AWS S3, GCS) | "Bring your own storage" |
| **Self-hosted** | Customer cloud | Customer cloud | Full customer ownership |

Our cloud infrastructure runs on **Microsoft Azure**. Default region: **East US**. Region selection
MUST be exposed to operators and customers; no region MUST be hardcoded in application logic.

---

## Engineering Principles

### I. Local-First Development

The entire stack MUST run locally before any commit is pushed to `origin` and before any cloud
deployment is attempted. "It works in CI" is not a substitute for "it works locally."

- Docker Compose is the local development environment. Every service, dependency (database,
  storage emulator, message broker), and sidecar MUST be startable with `docker compose up`.
- A new contributor MUST be able to go from `git clone` to a running stack by following
  `docs/quickstart.md` — no undocumented manual steps permitted.
- Features MUST be validated locally against the full Docker Compose stack before a pull request
  is opened.

### II. Security at Every Layer

Security is a first-class engineering concern, not a post-launch checkbox. Every design decision
MUST be evaluated through a security lens.

- **Authentication & authorisation**: all API endpoints MUST require authentication. Authorisation
  checks MUST be enforced server-side; client-side enforcement alone is never sufficient.
- **Secrets**: secrets, API keys, and connection strings MUST never appear in source code,
  committed configuration, or container images. Use environment variables (`.env` locally,
  a secrets manager in cloud environments).
- **Static analysis**: `bandit` MUST be run on every working branch and MUST pass before a pull
  request is created. Any `bandit` finding MUST be resolved or explicitly suppressed with a
  documented rationale (`# nosec: <reason>`).
- **Supply chain**: all production dependencies MUST be pinned in `pyproject.toml`. The
  `openkb-core` package MUST be installed from a pinned git tag — floating `main` or `develop`
  references are forbidden in non-development environments.
- **Input validation**: all external inputs (API request bodies, environment variables, storage
  payloads) MUST be validated with Pydantic before use.
- **Network exposure**: services MUST expose only the ports they require. Internal services MUST
  NOT be reachable from the public internet without an authenticated gateway.

### III. Observability

Every service component MUST emit structured, queryable signals across all three pillars:

- **Logging**: use the standard-library `logging` module with module-level loggers
  (`logger = logging.getLogger(__name__)`). Log at appropriate levels (DEBUG, INFO, WARNING,
  ERROR, CRITICAL). Do NOT use `print` for diagnostic output in library or service code.
  Logs MUST be structured (JSON format in deployed environments).
- **Metrics**: expose a `/metrics` endpoint (Prometheus format) from every long-running service.
  Track request counts, error rates, latency histograms, and queue depths at minimum.
- **Tracing**: instrument cross-service calls with distributed trace context propagation (e.g.,
  OpenTelemetry). Trace context MUST be forwarded from `generator_api` to `compiler_worker`
  and to `openkb serve` sidecars.
- **Health checks**: every service MUST expose `/health` (liveness) and `/ready` (readiness)
  endpoints. Readiness MUST check connectivity to all critical dependencies.

### IV. Per-Customer Isolation

In all three deployment models, customer data and processes MUST be strictly isolated.

- **Data isolation**: each knowledge base (KB) MUST have its own storage namespace (prefix,
  container, or bucket). Cross-KB data access at the storage layer MUST be architecturally
  impossible, not merely access-controlled.
- **Process isolation**: each active KB MUST run its own `openkb serve` sidecar process. Sidecars
  MUST NOT share in-memory state across customers or KBs.
- **Credential isolation**: per-customer storage credentials and secrets MUST be scoped to that
  customer. A compromise of one customer's credentials MUST NOT expose another customer's data.
- **Audit trail**: all data access and mutation events MUST be logged with customer ID, KB ID,
  actor identity, and timestamp to support audit requirements.
- **Scratch/temp isolation**: temporary files and scratch directories MUST be per-KB and MUST be
  cleaned up after each job. Shared `/tmp` usage that could leak data between KBs is forbidden.

### V. Enterprise Compliance Posture

The platform targets enterprise customers with regulated workloads. Compliance readiness MUST be
built in from the start, not retrofitted.

- **SOC 2 readiness**: implement and document controls for the five Trust Service Criteria
  (Security, Availability, Processing Integrity, Confidentiality, Privacy) as features are built.
- **GDPR readiness**: personal data MUST be identifiable and deletable on request. Data residency
  requirements MUST be honoured via region selection. Data MUST NOT leave the customer's chosen
  region without explicit consent.
- **Audit trails**: all privileged operations (compilation runs, document ingestion, KB creation,
  credential changes) MUST produce immutable audit log entries. Audit logs MUST be retained per
  policy and MUST NOT be editable by application code.
- **Encryption**: data MUST be encrypted at rest and in transit. Use provider-managed encryption
  as a minimum; customer-managed keys MUST be supportable for Hybrid and Self-hosted deployments.

### VI. Configurability

The platform MUST support meaningfully different configurations across deployment models and
customer environments without code changes.

- All tuneable parameters (storage backends, LLM endpoints, concurrency limits, retention
  policies, feature flags) MUST be driven by configuration, not hardcoded.
- Configuration MUST be YAML-based (`config.yaml`) with clearly documented defaults. A
  `DEFAULT_CONFIG` dict MUST serve as the authoritative fallback.
- Deployment-model-specific behaviour (e.g., "use customer-provided storage credentials in
  Hybrid mode") MUST be gated on configuration keys, not environment detection heuristics.
- Sensitive configuration values (connection strings, API keys) MUST be loaded from environment
  variables; they MUST NOT appear in YAML files.

### VII. Layered Architecture and Async-First I/O

The system is divided into two stable layers:

- **Foundation layer** (`compiler_worker` + `openkb compile`): compiles documents, builds the
  knowledge index, and manages persistent state (wiki, vector store, configuration).
- **Generator layer** (`generator_api` + `openkb serve` sidecars): serves queries and
  conversations against the compiled foundation.

Layer dependencies MUST flow downward only. The generator layer consumes the foundation; it MUST
NOT write back to foundation state. Cross-layer communication uses explicit interfaces (HTTP,
queue messages), not shared in-memory globals.

All I/O-bound operations — LLM calls, storage reads/writes, queue polling, sidecar HTTP calls —
MUST use `async`/`await`. Synchronous wrappers are acceptable only at process entry points.
Concurrent operations (e.g., batched document compilation) MUST use `asyncio.gather` or
equivalent and MUST be protected against partial-failure scenarios.

### VIII. Test Discipline

Tests are a delivery requirement, not an afterthought.

- Every module MUST have a corresponding test file. New behaviour MUST be accompanied by tests
  before a pull request is merged.
- Tests MUST be structured as:
  - **Unit tests** for pure logic (`tests/unit/`)
  - **Integration tests** for service interactions (`tests/integration/`)
  - **Isolation tests** for cross-KB contamination guarantees (`tests/isolation/`)
- Use `pytest` with `pytest-asyncio` for async tests. Mocks are permitted for external services
  (LLM providers, cloud storage); mocks MUST NOT paper over internal business logic.
- Test files MUST mirror the source tree structure.
- `ruff` (lint + format) and `bandit` checks MUST pass locally before any pull request is opened.
  These checks MUST also run in GitHub Actions CI on every push to a feature branch and on every
  PR targeting `develop`.

---

## Technical Standards

### Language and Runtime

- **Python >= 3.12**. `pyproject.toml` MUST declare `requires-python = ">=3.12"`.
- `from __future__ import annotations` MUST be present in every Python module.
- Type-annotate all public functions and class attributes. Avoid `Any` except at genuine
  boundaries (e.g., raw YAML payloads); document the reason when `Any` is used.

### Package Management

- **`uv`** is the sole package manager. Use `uv add`, `uv run`, `uv sync`. Do NOT invoke `pip`
  directly. All dependency changes MUST go through `uv` and MUST update `uv.lock`.

### Code Quality Gates

| Tool | Purpose | Gate |
|------|---------|------|
| `ruff` | Formatting and linting | MUST pass before PR creation |
| `bandit` | Security static analysis | MUST pass before PR creation |
| `pytest` | Test execution | MUST pass in CI on every PR |

Run locally: `uv run ruff check . && uv run ruff format --check . && uv run bandit -r . && uv run pytest`

### API and Service Standards

- FastAPI route handlers MUST use Pydantic models for request/response bodies. Raw `dict` returns
  from route handlers are forbidden.
- All API errors MUST return structured JSON with `detail`, `error_code`, and (where applicable)
  `request_id` fields.
- The `openkb serve` sidecar subprocess MUST be managed through a lifecycle manager; it MUST NOT
  be spawned ad-hoc in route handlers.

### Storage

- Storage backend implementations MUST conform to a common abstract interface so that Azure Blob,
  AWS S3, and GCS are interchangeable without application logic changes.
- File writes that affect knowledge-base state MUST be atomic (write-to-temp, then rename/commit).

### Azure Deployment

- Deployment target: **Azure Kubernetes Service (AKS)** or **Azure Container Apps**. Both MUST
  be supportable; infrastructure MUST not encode assumptions that break either target.
- Azure region MUST be configurable per environment; default is **East US**.
- Environments: `dev`, `uat`, `prd`. Only `dev` is initially active; CI failures against `uat`
  and `prd` are acceptable until those environments are provisioned.

---

## Repository Architecture

This repository (`openkb-platform`) hosts two primary services:

| Component | Location | Role |
|-----------|----------|------|
| `generator_api` | `generator_api/` | FastAPI service; manages `openkb serve` sidecar lifecycle; serves query/chat requests |
| `compiler_worker` | `compiler_worker/` | Async Postgres queue consumer; runs `openkb compile` per document |
| `openkb` sidecar | runtime subprocess | One `openkb serve` process per active KB; spawned on-demand by `generator_api` |

**openkb-core dependency**: `openkb-core` (providing `openkb compile`, `openkb serve`, and the
Python SDK) is consumed as a versioned pip dependency installed from a pinned GitHub tag. It MUST
NOT be edited in this repository. Feature work requiring `openkb-core` changes MUST be done in
that repository first, tagged, and the tag updated here.

**Local stack**: `docker-compose.yml` at the repository root MUST provide a complete local
development environment including Postgres, Azure Blob emulator (Azurite), and all application
services. No external cloud dependency MUST be required to run the stack locally.

---

## Development Workflow

### Branch Strategy (Git Flow)

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready releases only; merged from `develop` at release |
| `develop` | Default integration branch; all feature PRs target this branch |
| `feature/<name>` | Individual feature or fix branches; branched from `develop` |

- Feature branches MUST be branched from `develop` and merged back to `develop` via pull request.
- `main` receives merges from `develop` only at release boundaries.
- Direct commits to `main` or `develop` are forbidden (use PRs).

### Quality Gates for Pull Requests

A pull request MUST NOT be merged unless all of the following pass:

1. `ruff check .` — zero linting errors
2. `ruff format --check .` — zero formatting violations
3. `bandit -r .` — zero unresolved security findings
4. `pytest` — all tests pass in CI
5. Constitution Check — reviewer confirms the change complies with this document
6. Local validation — author confirms the stack runs locally end-to-end

### CI/CD

- **Platform**: GitHub Actions
- **Triggers**: push to any `feature/*` branch; pull request targeting `develop`; merge to `main`
- **Pipeline stages**: lint → security scan → unit tests → integration tests → build images →
  deploy to `dev` (on merge to `develop`) → deploy to `uat`/`prd` (on merge to `main`, gated)
- Deployment failures to `uat` or `prd` are acceptable while those environments are not yet
  provisioned; CI MUST NOT block `dev` deployments due to missing upper-environment config.

---

## Documentation and Style Standards

- All documentation MUST be maintained in the `docs/` directory. An index file `docs/index.md`
  MUST exist and link to all major documentation pages.
- Diagrams MUST use **Mermaid**. ASCII-art diagrams are forbidden.
- Commit messages MUST be clear, professional, and follow Conventional Commits format
  (e.g., `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`). Emojis in commit messages are
  forbidden. Vague messages ("fix stuff", "WIP", "misc") are forbidden.
- Emojis are forbidden in all documentation files.
- Public-facing documentation MUST be reviewed for accuracy whenever the behaviour it describes
  changes. Stale documentation is a bug.

---

## Governance

This constitution supersedes all prior informal practices, conventions, and READMEs in this
repository. When this document conflicts with other guidance, this document wins.

### Amendment Procedure

1. Propose the amendment with a documented rationale (PR description or ADR in `docs/`).
2. Determine the version bump:
   - **MAJOR**: backward-incompatible governance change; removal or fundamental redefinition of
     a principle.
   - **MINOR**: new principle or section added; material expansion of existing guidance.
   - **PATCH**: clarification, wording correction, or non-semantic refinement.
3. Update this file — increment the version, update `Last Amended` date, add an entry to the
   Amendment Log below.
4. Propagate changes to affected templates (see Sync Impact Report at top of this file).
5. The amendment lands in the same PR as the change it governs.

### Compliance Reviews

- All pull request reviewers MUST verify compliance with this constitution.
- Non-compliance findings MUST be flagged as blocking comments, not suggestions.
- The Constitution Check gate in plan templates MUST be re-verified after Phase 1 design is
  complete.

---

<!--
AMENDMENT LOG
=============
v2.0.0 (2026-06-25): Complete rework for openkb-platform. Introduced Product Positioning
  (three deployment models, Azure cloud), eight engineering principles (Local-First, Security,
  Observability, Isolation, Compliance, Configurability, Layered Architecture + Async, Test
  Discipline), Repository Architecture section, Documentation & Style Standards, and Git Flow
  governance. Supersedes v1.1.0 general-purpose constitution.

v1.1.0 (2026-06-21): Raised minimum Python from >=3.10 to 3.12. Mandated uv as sole package
  manager; pip usage prohibited.

v1.0.0 (2026-06-19): Initial constitution authoring.
-->


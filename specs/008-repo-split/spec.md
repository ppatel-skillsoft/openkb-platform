# Feature Specification: Repository Split — Core / Platform / MCP

**Feature Branch**: `008-repo-split`
**Created**: 2026-06-22
**Status**: Draft

## Overview

OpenKB is built on top of [VectifyAI/OpenKB](https://github.com/VectifyAI/OpenKB) — an open-source Python package providing the core CLI pipeline (ingest, compile, query). As the platform grows, the mono-repo structure makes it increasingly difficult to pull upstream improvements: every `git fetch upstream` risks conflicts between upstream changes to `openkb/` and our own additions (`api/`, `storage/`, `services/`). Additionally, the generator-api, compiler-worker, and future MCP server have independent deployment lifecycles and concerns.

This spec defines the migration from one mono-repo into **three focused repositories**, each with a single clear responsibility, connected by versioned pip dependencies and HTTP contracts.

---

## Target State

```
VectifyAI/OpenKB  (upstream, read-only reference)
       ↓  fork + upstream remote
ppatel-skillsoft/openkb-core        pip package (published via GitHub Packages / PyPI)
       ↓  pip install openkb-core==X.Y.Z
ppatel-skillsoft/openkb-platform    generator_api + compiler_worker + alembic + docker-compose
       ↓  HTTP REST client only
ppatel-skillsoft/openkb-mcp         FastMCP server (future — spec 009)
```

### Repository Responsibilities

| Repo | Contents | Versioning | Published as |
|---|---|---|---|
| `openkb-core` | `openkb/` Python package — CLI, indexer, converter, compiler, API routes, storage backends | semver tags | `openkb-core` pip package |
| `openkb-platform` | `generator_api/`, `compiler_worker/`, `alembic/`, `docker-compose.yml`, `tests/` | semver tags | Docker images |
| `openkb-mcp` | FastMCP server, MCP tool definitions | semver tags | Docker image |

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Developer syncs upstream OpenKB changes (Priority: P1)

A developer wants to pull new features or bug fixes from VectifyAI/OpenKB into `openkb-core` without disrupting the platform.

**Independent Test**: Run `git fetch upstream && git merge upstream/main` in `openkb-core`. Zero conflicts in `openkb/api/`, `openkb/storage/`, `openkb/services/` (our additions). Any conflicts are confined to upstream-owned files (`cli.py`, `converter.py`, `indexer.py`). Tests pass after merge.

**Acceptance Scenarios**:

1. **Given** VectifyAI/OpenKB has merged a new release, **When** a developer runs `git fetch upstream && git merge upstream/main` in `openkb-core`, **Then** the merge completes with conflicts only in files owned by upstream (no conflicts in `api/`, `storage/`, `services/`).
2. **Given** a successful upstream merge, **When** the developer tags `openkb-core` as `vX.Y.Z` and pushes, **Then** the pip package is automatically published via GitHub Actions.
3. **Given** a new `openkb-core` version is published, **When** a developer bumps the pin in `openkb-platform/pyproject.toml` and runs `uv sync`, **Then** the platform test suite passes without modification.

---

### User Story 2 — Platform deploys independently of core (Priority: P1)

The generator-api and compiler-worker can be released and deployed without touching `openkb-core`.

**Acceptance Scenarios**:

1. **Given** `openkb-core` is pinned at `v1.0.0` in `openkb-platform`, **When** a developer makes a change to `generator_api/router.py` and tags `openkb-platform` as `v2.1.0`, **Then** the Docker image is built and published without rebuilding or re-tagging `openkb-core`.
2. **Given** `openkb-platform` is deployed, **When** the isolation test suite runs (`docker compose --profile test run --rm isolation-tests`), **Then** all 11 tests pass.

---

### User Story 3 — New developer onboards quickly (Priority: P2)

A developer clones a single repo and has a running local stack within 15 minutes.

**Acceptance Scenarios**:

1. **Given** a developer clones `openkb-platform`, **When** they run `docker compose up`, **Then** all services start; `openkb-core` is pulled as a pip dependency during Docker build — no manual clone of `openkb-core` is required.
2. **Given** `openkb-core` is not available on public PyPI, **When** the Docker build runs, **Then** `uv pip install` fetches `openkb-core` from the GitHub Packages registry or a pinned git URL.

---

### User Story 4 — CI enforces version pin discipline (Priority: P2)

Unpinned or floating dependencies are rejected in CI.

**Acceptance Scenarios**:

1. **Given** a PR changes `openkb-core` dependency to `openkb-core>=1.0` (unpinned range), **When** the CI lint step runs, **Then** the build fails with a message indicating exact pinning is required.
2. **Given** `openkb-core` is pinned to an exact version in `pyproject.toml`, **When** CI runs `uv sync --frozen`, **Then** the lockfile is verified and the build proceeds.

---

## Functional Requirements

| ID | Requirement |
|---|---|
| FR-001 | `openkb-core` repo is a fork of VectifyAI/OpenKB with `upstream` remote configured |
| FR-002 | `openkb-core` contains `openkb/` package root verbatim from current mono-repo (including `api/`, `storage/`, `services/`) |
| FR-003 | `openkb-core` publishes a pip-installable package on every semver tag via GitHub Actions |
| FR-004 | `openkb-platform` repo contains `generator_api/`, `compiler_worker/`, `alembic/`, `docker-compose.yml`, `scripts/`, `specs/`, `tests/` |
| FR-005 | `openkb-platform/pyproject.toml` pins `openkb-core` to an exact version (no ranges) |
| FR-006 | All Docker images in `openkb-platform` install `openkb-core` via pip (not by copying source) |
| FR-007 | The upstream sync workflow is documented in `openkb-core/docs/UPSTREAM_SYNC.md` |
| FR-008 | `openkb-platform` retains all 11 isolation tests passing after migration |
| FR-009 | The mono-repo (`ppatel-skillsoft/OpenKB`) is archived and its README redirects to the two new repos |
| FR-010 | `openkb-platform` GitHub Actions CI runs `docker compose --profile test run --rm isolation-tests` on every PR to `develop` |

---

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-001 | Local-first: `docker compose up` in `openkb-platform` must work with no internet access after initial `docker pull` (all deps baked into images) |
| NFR-002 | Upstream sync must be achievable by a single developer in < 2 hours including test run |
| NFR-003 | `openkb-core` package must install cleanly into a fresh Python 3.12 venv |
| NFR-004 | No secrets committed to either repo |
| NFR-005 | Both repos must have branch protection on `main` and `develop` |

---

## Out of Scope

- `openkb-mcp` repo creation (this is spec 009)
- Publishing `openkb-core` to public PyPI (GitHub Packages is sufficient for now)
- Automated upstream sync (manual workflow is acceptable for Phase 0)
- Kubernetes / cloud deployment (local Docker Compose only, per project constitution)

---

## Constraints

- **Local-first**: All services runnable via Docker Compose with no real Azure services required
- **Exact pinning**: All production dependencies pinned to exact versions (project convention)
- **Python ≥ 3.12**: Both repos target Python 3.12
- **uv**: Package management uses `uv` throughout (not pip directly)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Upstream sync conflict in `cli.py` | Medium | Medium | Keep `openkb/api/`, `storage/`, `services/` strictly separated from upstream-owned files; document ownership in `CODEOWNERS` |
| GitHub Packages auth complexity in Docker builds | Medium | Low | Use a `GITHUB_TOKEN` build arg or a pre-authenticated `.netrc`; document in `openkb-platform` README |
| Isolation tests fail after migration | Low | High | Run isolation tests as the final migration acceptance criterion before archiving mono-repo |
| `openkb-core` git URL pin becomes stale | Low | Medium | Pin to immutable git tags (not branches); CI `uv sync --frozen` catches drift |

---

## Definition of Done

- [ ] `ppatel-skillsoft/openkb-core` exists, `upstream` remote points to VectifyAI/OpenKB, `openkb/` package installs cleanly
- [ ] `ppatel-skillsoft/openkb-platform` exists, all services start with `docker compose up`, all 11 isolation tests pass
- [ ] `openkb-core` GitHub Actions publishes a pip package on tag push
- [ ] `openkb-platform` GitHub Actions CI runs isolation tests on PR
- [ ] `UPSTREAM_SYNC.md` documents the sync workflow step-by-step
- [ ] Mono-repo `ppatel-skillsoft/OpenKB` archived with README redirect

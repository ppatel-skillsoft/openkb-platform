# Implementation Plan: Repository Split — Core / Platform / MCP

**Branch**: `feature/008-repo-split` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)

## Summary

Migrate from the current mono-repo into two active repositories:

1. **`openkb-core`** — the `openkb/` Python package (fork of VectifyAI/OpenKB), published as a pip package via GitHub Packages. Has an `upstream` remote configured so upstream changes can be merged periodically.
2. **`openkb-platform`** — `generator_api/`, `compiler_worker/`, `alembic/`, `docker-compose.yml`, `tests/`, `specs/`. Consumes `openkb-core` as a versioned pip dependency. All Docker images install core via pip.

The mono-repo is archived after migration is verified. The MCP server (`openkb-mcp`) is out of scope for this spec (see spec 009).

---

## Technical Context

**Current state**: Single repo at `ppatel-skillsoft/OpenKB`. The `openkb/` package is the upstream core with our additions (`api/`, `storage/`, `services/`). Platform code (`generator_api/`, `compiler_worker/`) is entirely our own and consumes `openkb` as a subprocess via `openkb serve`.

**Key insight**: Platform code never imports `openkb` Python modules directly — it calls `openkb serve` as a subprocess (sidecar) and communicates via HTTP. This means the pip dependency boundary is clean: `openkb-core` is installed in Docker images and provides the `openkb` CLI entrypoint.

**Dependency graph**:
```
openkb-core (pip package)
    installed into →  Dockerfile (generator-api image)
                      Dockerfile.compiler-worker
                      Dockerfile.generator-api
                      tests/isolation/Dockerfile

openkb-platform
    depends on → openkb-core @ git+https://github.com/ppatel-skillsoft/openkb-core@vX.Y.Z
    exposes → generator-api HTTP, compiler-worker (background), isolation-tests
```

---

## Ownership Boundaries (critical for upstream sync)

Files that belong to **upstream** (VectifyAI/OpenKB — expect conflicts during sync):
```
openkb/cli.py
openkb/config.py
openkb/converter.py
openkb/indexer.py
openkb/locks.py
openkb/schema.py
openkb/state.py
openkb/url_ingest.py
openkb/watcher.py
openkb/agent/
openkb/deck/
openkb/prompts/
openkb/skill/
```

Files that belong to **us** (never modified by upstream — conflict-free):
```
openkb/api/          ← added in spec 001
openkb/storage/      ← added in spec 001
openkb/services/     ← added in spec 001
```

A `CODEOWNERS` file in `openkb-core` documents this split.

---

## Phase 0 — Research & Decisions

Decisions already made (see conversation context):

| Decision | Choice | Rationale |
|---|---|---|
| Dependency mechanism | pip install from git tag | Simpler than submodules; immutable tags prevent drift |
| Package registry | GitHub Packages (ghcr.io / GitHub Package Registry) | No public PyPI needed; auth via GITHUB_TOKEN |
| Upstream sync | Manual (`git fetch upstream && git merge`) | Automated sync risks silent breakage; quarterly cadence |
| MCP server | Separate spec (009) | Out of scope here |
| Mono-repo fate | Archived + README redirect | Preserves git history |

---

## Phase 1 — Create `openkb-core` Repository

### Steps

1. Create `ppatel-skillsoft/openkb-core` on GitHub (empty, no README)
2. From the mono-repo, extract the `openkb/` directory as the new repo root:
   ```bash
   git subtree split --prefix=openkb -b openkb-core-branch
   cd /tmp && git clone ppatel-skillsoft/openkb-core
   cd openkb-core && git pull /path/to/mono-repo openkb-core-branch
   ```
3. Add `upstream` remote:
   ```bash
   git remote add upstream https://github.com/VectifyAI/OpenKB
   git fetch upstream
   ```
4. Create `pyproject.toml` at repo root (already exists as part of `openkb/` — verify it builds standalone)
5. Add `CODEOWNERS` documenting upstream vs our file ownership
6. Add `docs/UPSTREAM_SYNC.md` with step-by-step sync runbook
7. Create GitHub Actions workflow: on push of `vX.Y.Z` tag → build wheel → publish to GitHub Packages
8. Tag initial release `v0.1.0`, verify pip install succeeds from GitHub Packages

---

## Phase 2 — Create `openkb-platform` Repository

### Steps

1. Create `ppatel-skillsoft/openkb-platform` on GitHub (empty)
2. Extract platform code from mono-repo (everything except `openkb/`):
   ```
   generator_api/
   compiler_worker/
   alembic/
   tests/
   specs/
   scripts/
   docker-compose.yml
   Dockerfile
   Dockerfile.compiler-worker
   Dockerfile.generator-api
   .dockerignore
   .env.example
   .env.azure.example
   .env.docker
   alembic.ini
   pyproject.toml  ← update deps
   uv.lock         ← regenerate after dep change
   ```
3. Update `pyproject.toml` in `openkb-platform`:
   - Replace `openkb` local source with `openkb-core @ git+https://github.com/ppatel-skillsoft/openkb-core@v0.1.0`
   - Remove `[tool.hatch.build]` source inclusion of `openkb/`
4. Update all `Dockerfile*`:
   - Remove `COPY openkb/ ./openkb/`
   - Ensure `uv pip install` pulls `openkb-core` from GitHub Packages
5. Update `tests/isolation/Dockerfile` similarly
6. Run `uv sync` → regenerate `uv.lock`
7. Run `docker compose build` → verify all images build
8. Run `docker compose up` → verify stack healthy
9. Run `docker compose --profile test run --rm isolation-tests` → all 11 tests must pass

---

## Phase 3 — CI & Branch Protection

### `openkb-core` CI

```yaml
# .github/workflows/publish.yml
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv build
      - run: uv publish --index-url https://upload.pypi.org/legacy/  # or GitHub Packages
```

### `openkb-platform` CI

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  isolation-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build
      - run: docker compose up -d
      - run: docker compose --profile test run --rm isolation-tests
      - run: docker compose down -v
```

### Branch protection (both repos)
- `main`: require PR, require CI green, no force push
- `develop`: require PR, require CI green

---

## Phase 4 — Archive Mono-repo

1. Update `ppatel-skillsoft/OpenKB` README to:
   ```markdown
   # ⚠️ This repository has been split

   - **openkb-core**: https://github.com/ppatel-skillsoft/openkb-core (OpenKB Python package)
   - **openkb-platform**: https://github.com/ppatel-skillsoft/openkb-platform (API, worker, Docker Compose)
   ```
2. Archive the repo on GitHub (Settings → Archive)

---

## Upstream Sync Workflow (steady state)

Once split, syncing upstream changes into `openkb-core`:

```bash
# 1. Fetch upstream
git fetch upstream

# 2. Create sync branch
git checkout develop
git checkout -b sync/upstream-$(date +%Y-%m-%d)

# 3. Merge — conflicts expected only in upstream-owned files
git merge upstream/main

# 4. Resolve conflicts, run tests
uv run pytest
openkb --help   # smoke test CLI still works

# 5. PR → develop → tag new version
git tag v0.X.Y
git push origin v0.X.Y

# 6. In openkb-platform: bump pin
# pyproject.toml: openkb-core @ git+...@v0.X.Y
uv sync
docker compose build
docker compose --profile test run --rm isolation-tests
```

---

## Project Structure After Migration

### `openkb-core`
```
openkb/               ← package root (was openkb/ in mono-repo)
├── cli.py
├── api/
├── storage/
├── services/
├── ...
docs/
└── UPSTREAM_SYNC.md
CODEOWNERS
pyproject.toml
.github/workflows/publish.yml
```

### `openkb-platform`
```
generator_api/
compiler_worker/
alembic/
tests/
specs/
scripts/
docker-compose.yml
Dockerfile
Dockerfile.compiler-worker
Dockerfile.generator-api
pyproject.toml        ← openkb-core pinned by git tag
uv.lock
.github/workflows/ci.yml
```

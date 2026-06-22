# Tasks: 008 — Repository Split (Core / Platform / MCP)

**Feature**: `008-repo-split` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Generated**: 2026-06-22

---

## Summary

- **Total tasks**: 16
- **Phases**: Phase 1 (core repo), Phase 2 (platform repo), Phase 3 (CI), Phase 4 (archive)
- **Exit criterion**: All 11 isolation tests pass in `openkb-platform` using `openkb-core` as a pip dependency
- **Prerequisite**: `develop` branch is up-to-date and all tests pass in mono-repo before starting

---

## Phase 1 — Create `openkb-core` Repository

> Extract the `openkb/` Python package into its own repo, connect upstream, publish pip package.

- [ ] T001 Create empty `ppatel-skillsoft/openkb-core` repo on GitHub (no README, no .gitignore via UI). Locally, use `git subtree split --prefix=openkb -b core-split` in the mono-repo to produce a branch whose root is the `openkb/` directory. Push this branch to `openkb-core` as `main`.

- [ ] T002 In `openkb-core`: add `upstream` remote pointing to `https://github.com/VectifyAI/OpenKB`. Run `git fetch upstream`. Do NOT merge yet — this is setup only. Verify `git remote -v` shows both `origin` and `upstream`.

- [ ] T003 Add `CODEOWNERS` file to `openkb-core` root documenting the ownership boundary:
  - **upstream-owned** (expect merge conflicts): `cli.py`, `config.py`, `converter.py`, `indexer.py`, `locks.py`, `schema.py`, `state.py`, `url_ingest.py`, `watcher.py`, `agent/`, `deck/`, `prompts/`, `skill/`
  - **our additions** (no upstream conflicts expected): `api/`, `storage/`, `services/`

- [ ] T004 Create `docs/UPSTREAM_SYNC.md` in `openkb-core` with the full step-by-step sync runbook from [plan.md §Upstream Sync Workflow](./plan.md). Include: fetch, branch naming convention (`sync/upstream-YYYY-MM-DD`), conflict resolution guidance, test commands, tag format, and platform pin-bump steps.

- [ ] T005 Create `.github/workflows/publish.yml` in `openkb-core`:
  - Trigger: `push` on tags matching `v*`
  - Steps: `actions/checkout@v4` → install `uv` → `uv build` → publish wheel to GitHub Packages (using `GITHUB_TOKEN`)
  - Verify by pushing tag `v0.1.0` and confirming package appears in GitHub Packages registry

- [ ] T006 Verify `openkb-core` installs cleanly in a fresh venv:
  ```bash
  python -m venv /tmp/test-core-venv
  source /tmp/test-core-venv/bin/activate
  pip install git+https://github.com/ppatel-skillsoft/openkb-core@v0.1.0
  openkb --help
  ```
  Must show the Click help output with no import errors.

---

## Phase 2 — Create `openkb-platform` Repository

> Extract platform code into its own repo, update deps to consume `openkb-core` via pip.

- [ ] T007 Create empty `ppatel-skillsoft/openkb-platform` repo on GitHub. Locally, create a new git repo from the mono-repo excluding the `openkb/` directory. Use `git filter-repo` or a fresh init + selective file copy to produce a clean history. Push to `openkb-platform` as `main` and `develop`.

  Files to include:
  ```
  generator_api/   compiler_worker/   alembic/   tests/
  specs/           scripts/           docker-compose.yml
  Dockerfile       Dockerfile.compiler-worker    Dockerfile.generator-api
  .dockerignore    .env.example       .env.azure.example   .env.docker
  alembic.ini      pyproject.toml     uv.lock    README.md   LICENSE
  .github/         .gitignore
  ```

- [ ] T008 Update `pyproject.toml` in `openkb-platform`:
  - Replace `openkb` (local source / editable) with:
    `"openkb-core @ git+https://github.com/ppatel-skillsoft/openkb-core@v0.1.0"`
  - Remove any `[tool.hatch.build]` or path references to local `openkb/` source
  - Remove `openkb` from `[project.name]` — this package is now `openkb-platform`
  - Run `uv sync` to regenerate `uv.lock`

- [ ] T009 Update `Dockerfile` (openkb sidecar image used by generator-api):
  - Remove `COPY openkb/ ./openkb/`
  - Ensure `uv pip install` (or `uv sync`) pulls `openkb-core` from GitHub Packages
  - Add `--extra-index-url` or `.netrc` config for GitHub Packages auth if required
  - Build and verify: `docker build -t openkb-core-test . && docker run --rm openkb-core-test openkb --help`

- [ ] T010 Update `Dockerfile.compiler-worker` and `Dockerfile.generator-api` with same changes as T009 (remove `COPY openkb/`, rely on pip for `openkb-core`).

- [ ] T011 Update `tests/isolation/Dockerfile`:
  - Remove `COPY openkb/ ./openkb/`
  - Verify `openkb-core` is pulled as a dependency during build
  - Build image: `docker build -f tests/isolation/Dockerfile -t isolation-tests-test .`

- [ ] T012 Run full stack verification in `openkb-platform`:
  ```bash
  docker compose build          # all images must build successfully
  docker compose up -d          # all services healthy
  docker compose --profile test run --rm isolation-tests
  ```
  All 11 isolation tests must pass. This is the migration acceptance criterion (FR-008).

---

## Phase 3 — CI & Branch Protection

- [ ] T013 Create `.github/workflows/ci.yml` in `openkb-platform`:
  - Trigger: `push` and `pull_request` on `develop` and `main`
  - Steps: `actions/checkout@v4` → `docker compose build` → `docker compose up -d` → `docker compose --profile test run --rm isolation-tests` → `docker compose down -v`
  - Requires Docker Compose v2 on the runner (use `ubuntu-latest` — it includes Docker)

- [ ] T014 Enable branch protection in both repos:
  - `openkb-core`: `main` and `develop` — require PR, require CI green, no force push
  - `openkb-platform`: `main` and `develop` — require PR, require status check `isolation-tests` to be green, no force push

---

## Phase 4 — Archive Mono-repo

- [ ] T015 Update `ppatel-skillsoft/OpenKB` README to prominently redirect:
  ```markdown
  # ⚠️ This repository has been split into focused repos

  | Repository | Purpose |
  |---|---|
  | [openkb-core](https://github.com/ppatel-skillsoft/openkb-core) | OpenKB Python package (CLI, indexer, API) |
  | [openkb-platform](https://github.com/ppatel-skillsoft/openkb-platform) | Generator API, Compiler Worker, Docker Compose stack |

  This repository is archived. All future development happens in the repos above.
  ```
  Commit and push this change before archiving.

- [ ] T016 Archive `ppatel-skillsoft/OpenKB` on GitHub via Settings → Archive repository. Verify the repo is read-only. Verify both new repos are accessible and the redirect README is visible to anonymous visitors.

---

## Dependency Graph

```
T001 (core repo created)
  └─→ T002 (upstream remote)
  └─→ T003 (CODEOWNERS)
  └─→ T004 (UPSTREAM_SYNC.md)
  └─→ T005 (publish workflow)
        └─→ T006 (verify install) ──────────────────────────────┐
                                                                 ↓
T007 (platform repo created)                              T008 (update pyproject)
  └─→ T008 (update pyproject dep) ─→ T009/T010/T011 (Dockerfiles)
                                          └─→ T012 (full stack + isolation tests) ← GATE
                                                └─→ T013 (CI workflow)
                                                └─→ T014 (branch protection)
                                                      └─→ T015 (README redirect)
                                                            └─→ T016 (archive mono-repo)
```

## Gate

**Do not proceed past T012 until all 11 isolation tests pass.** T015 and T016 (mono-repo archive) are irreversible — only execute them after T012 and T013 are verified green.

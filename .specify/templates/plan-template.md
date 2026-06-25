# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python >= 3.12 (`from __future__ import annotations` in every module)
**Primary Dependencies**: FastAPI, Pydantic, pytest, ruff, bandit; `openkb-core` at pinned git tag
**Storage**: PostgreSQL (job queue); Azure Blob / AWS S3 / GCS (document storage, per-customer)
**Testing**: pytest + pytest-asyncio; ruff + bandit gates MUST pass before PR
**Target Platform**: Docker Compose (local); AKS or Azure Container Apps (cloud)
**Project Type**: Multi-tenant SaaS platform (generator_api + compiler_worker services)
**Performance Goals**: [domain-specific — specify per feature, e.g., p95 query latency]
**Constraints**: Per-customer data and process isolation MUST be maintained at all times
**Scale/Scope**: [specify per feature — concurrent KB count, document throughput, etc.]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify the following against `.specify/memory/constitution.md` before proceeding:

| Check | Principle | Status |
|-------|-----------|--------|
| Local Docker Compose stack runs end-to-end | I. Local-First | [ ] |
| No secrets or API keys in source or config files | II. Security | [ ] |
| `bandit` passes with zero unresolved findings | II. Security / VIII. Test Discipline | [ ] |
| `ruff check` and `ruff format --check` pass | VIII. Test Discipline | [ ] |
| All new modules have corresponding test files | VIII. Test Discipline | [ ] |
| Per-KB data and process isolation is maintained | IV. Isolation | [ ] |
| Storage backend uses abstract interface (not cloud-specific) | VI. Configurability | [ ] |
| Logging uses `logging.getLogger(__name__)`, not `print` | III. Observability | [ ] |
| `/health` and `/ready` endpoints present (if new service) | III. Observability | [ ] |
| `openkb-core` dependency references a pinned git tag | II. Security | [ ] |
| Feature branch targets `develop`, not `main` | Git Flow | [ ] |
| All new behaviour covered by tests (unit + integration) | VIII. Test Discipline | [ ] |

**Violations requiring documented justification** (add to Complexity Tracking below if any):

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |

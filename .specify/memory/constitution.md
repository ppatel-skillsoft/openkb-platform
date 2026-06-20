<!--
SYNC IMPACT REPORT
==================
Version change: 0.0.0 (placeholder) → 1.0.0
Modified principles: N/A (initial authoring)
Added sections: Core Principles, Technical Standards, Development Workflow, Governance
Removed sections: all placeholder tokens
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ (Constitution Check section already present)
  - .specify/templates/spec-template.md ✅ (compatible with principles as written)
  - .specify/templates/tasks-template.md ✅ (no principle-driven changes required)
Deferred TODOs: none
-->

# OpenKB Constitution

## Core Principles

### I. Layered Architecture

The system is divided into clear, stable layers: a **foundation layer** that compiles and manages
persistent state (wiki, index, configuration), and **generator layers** that consume that foundation
to produce output (answers, conversations, skills, API responses). Layers communicate through
explicit interfaces, not shared mutable globals.

Each module MUST have a single clear responsibility. Cross-layer dependencies MUST flow downward
only. The CLI and API surfaces are thin adapters over a shared service core.

### II. CLI-First, API-Consistent

Every capability MUST be accessible from the command line. The CLI is the primary user interface
and the contract against which new features are defined first.

Where a FastAPI layer exists, it MUST expose the same operations and honour the same business rules
as the CLI. There MUST be no logic in route handlers that isn't already exercisable via the CLI or
shared services. Errors and structured output MUST follow consistent schemas across both surfaces.

### III. Async by Default for I/O

All I/O-bound operations — LLM calls, file reads/writes, network requests — MUST use `async`/`await`.
Synchronous wrappers over async code are acceptable only at CLI entry points. CPU-bound work
may remain synchronous but MUST be clearly documented.

Concurrent operations (e.g., batched LLM requests) MUST use `asyncio.gather` or equivalent rather
than sequential awaiting, and MUST be protected against partial-failure scenarios.

### IV. Test Coverage is Non-Negotiable

Every module MUST have a corresponding test file. New behaviour MUST be accompanied by tests before
a PR is merged. Tests SHOULD be structured as: unit tests for pure logic, integration tests for
service interactions, and CLI/API contract tests for surfaces.

Use `pytest` with `pytest-asyncio` for async tests. Mocks are allowed for external services (LLM
providers, network); they MUST NOT paper over internal business logic. Test files MUST mirror the
source tree structure.

### V. Supply-Chain Discipline

All production dependencies MUST be pinned to exact versions in `pyproject.toml`. Version bumps
MUST be deliberate, documented (inline comment stating why), and vetted before merging. Dev/optional
dependencies follow the same rule.

Secrets and API keys MUST never appear in source code or committed configuration. Use environment
variables loaded from `.env` (not committed) or a secrets manager.

### VI. Robustness and Graceful Degradation

Configuration MUST have safe defaults; missing or malformed config keys MUST log a warning and
fall back, never crash. User-facing errors MUST be actionable — they MUST indicate what went wrong
and what the user should do next.

File writes MUST be atomic (write-then-rename) when data integrity matters. Concurrent access to
shared state MUST be coordinated via explicit locks. Partial state is worse than no state.

## Technical Standards

- **Python ≥ 3.10**; use `from __future__ import annotations` in all modules.
- Use standard-library `logging` with module-level loggers (`logger = logging.getLogger(__name__)`).
  Do not use `print` for diagnostic output in library code.
- Type-annotate all public functions and class attributes. Avoid `Any` except at genuine
  boundaries (e.g., raw YAML payloads), and document why.
- Configuration MUST be YAML-based with a `DEFAULT_CONFIG` dict as the fallback; do not
  hardcode values inside business logic.
- FastAPI route handlers MUST use Pydantic models for request/response validation. No raw `dict`
  returns from route handlers.
- CLI commands MUST use Click. Arguments and options MUST have `--help` strings.

## Development Workflow

- Features are developed on branches. A feature is complete only when: the constitution check
  passes, tests pass, and the CLI/API contract is exercised by at least one test.
- PRs MUST NOT introduce dependencies without a rationale comment.
- Linting and type-checking MUST pass before merge. Breaking changes to public CLI commands or API
  routes require a version bump and migration note.
- Complexity MUST be justified. When a simpler alternative exists, it MUST be chosen unless there
  is a concrete, documented reason otherwise.

## Governance

This constitution supersedes all other informal practices. Amendments require: a documented
rationale, a version bump (MAJOR for principle changes, MINOR for additions, PATCH for
clarifications), and an update to this file before the change lands.

All code reviews MUST verify compliance with the principles above. Non-compliance MUST be flagged
as a blocking comment, not a suggestion.

**Version**: 1.0.0 | **Ratified**: 2026-06-19 | **Last Amended**: 2026-06-19

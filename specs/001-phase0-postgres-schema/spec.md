# Feature Specification: Phase 0 Postgres Schema Bootstrap

**Feature Branch**: `002-phase0-postgres-schema`
**Created**: 2026-06-21
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Schema Applied to a Fresh Database (Priority: P1)

A developer cloning the repository for the first time runs a single command that provisions a local Postgres instance and applies all Phase 0 migrations. Within minutes the database contains the `knowledge_bases`, `documents`, and `wiki_pages` tables with the correct columns, types, constraints, and indexes — and nothing else.

**Why this priority**: Every other Phase 0 service (`compiler-worker`, `generator-api`) depends on these tables existing. This is the unblocking step.

**Independent Test**: Can be fully tested by running the migration command against an empty Postgres database and verifying that all three tables are present with the defined columns and constraints; delivers a working data layer independently of any application code.

**Acceptance Scenarios**:

1. **Given** an empty Postgres database, **When** the developer runs the migration command, **Then** the three tables (`knowledge_bases`, `documents`, `wiki_pages`) are created with all specified columns, data types, primary keys, foreign keys, unique constraints, and indexes — and no other tables are created.
2. **Given** the migration has already been applied, **When** the developer runs the migration command again, **Then** the command completes successfully without error and the schema is unchanged (idempotent behaviour).
3. **Given** a migration is applied to an empty database, **When** the developer inspects table structure, **Then** every UUID primary key column defaults to a generated UUID, every `created_at` / `updated_at` column defaults to the current timestamp, and `deleted_at` is nullable with no default.

---

### User Story 2 — Local Development Environment Spun Up in One Step (Priority: P1)

A developer starting Phase 0 work runs a single compose-style command that launches a local Postgres container, waits for it to be ready, and applies the Phase 0 migrations automatically — leaving a fully usable development database without any manual SQL or configuration.

**Why this priority**: Reproducible local setup is a prerequisite for every developer contributing to Phase 0 services.

**Independent Test**: Can be tested on a clean machine by running the compose command and verifying the database is reachable with the correct schema applied.

**Acceptance Scenarios**:

1. **Given** Docker is available and the repository is cloned, **When** the developer runs the local-environment startup command, **Then** a Postgres container starts, the migrations are applied, and the developer can immediately connect to the database.
2. **Given** the local environment is running, **When** the developer stops and restarts it, **Then** previously applied migrations are not re-applied and any seed data persists across restarts (unless explicitly reset).
3. **Given** the local environment is running, **When** the developer runs the seed/fixture command, **Then** a scratch `knowledge_base` record and at least two `document` records are created, providing an immediately queryable dataset for development and manual testing.

---

### User Story 3 — Other Services Can Connect Using the Shared Session Factory (Priority: P2)

The `compiler-worker` and `generator-api` services import the connection/session factory provided by this feature and use it to query and write to the Phase 0 tables — without each service needing to implement its own database connection logic.

**Why this priority**: A shared connection factory eliminates duplication and ensures consistent connection behaviour across services; required before service integration tests can run.

**Independent Test**: Can be tested by importing the session factory from its published location and executing a simple SELECT against `knowledge_bases`; the query succeeds and returns results.

**Acceptance Scenarios**:

1. **Given** the Phase 0 database is running and the session factory is imported, **When** a service executes a query through the factory, **Then** the query returns correct results without requiring the service to manage connection strings or pool settings directly.
2. **Given** the database is temporarily unavailable, **When** a service attempts to obtain a connection, **Then** the factory returns a clear, actionable error rather than hanging indefinitely.
3. **Given** the production configuration (pointing to Azure Database for PostgreSQL Flexible Server) is provided, **When** the factory initialises, **Then** it connects successfully using the same interface used in local development — no code changes required between environments.

---

### User Story 4 — Schema Is Forward-Compatible with Phase 1 Additions (Priority: P2)

When the Phase 1 schema migration is authored (adding `organizations`, `users`, and related tables, plus `org_id` on `knowledge_bases` and `added_by` on `documents`), it applies cleanly on top of the Phase 0 schema via a new migration — no destructive rewrites, no existing data loss.

**Why this priority**: Architectural correctness now prevents painful schema rewrites later; validates that Phase 0 tables were designed with extension columns in mind.

**Independent Test**: Can be tested by authoring a stub Phase 1 migration that adds `org_id` (nullable UUID) to `knowledge_bases` and `added_by` (nullable UUID) to `documents` and verifying it applies without errors against a Phase 0 database.

**Acceptance Scenarios**:

1. **Given** the Phase 0 schema is applied with seed data present, **When** a Phase 1 migration that adds `org_id` to `knowledge_bases` and `added_by` to `documents` is run, **Then** the migration completes successfully, all existing rows have NULL values for the new columns, and no data is lost.
2. **Given** the Phase 0 migration history exists, **When** a developer lists the migration history, **Then** Phase 0 migrations are numbered/labelled distinctly from future Phase 1 migrations, making the migration sequence readable and auditable.

---

### Edge Cases

- What happens when the database already contains one or some of the three tables (partial schema state)? The migration command must detect the inconsistency and either complete the partial schema or fail with a clear diagnostic — never silently create duplicate structures.
- What happens when `kb_id` on `documents` or `wiki_pages` references a `knowledge_bases` row that does not exist? The foreign key constraint must reject the insert with an informative error.
- What happens when two `wiki_pages` records for the same `kb_id` have the same `slug`? The unique constraint `(kb_id, slug)` must reject the second insert.
- What happens when the seed/fixture command is run twice? It must either be idempotent (skip already-existing records) or clearly document that it requires a clean database.
- What happens when the `compilation_config` JSONB column is queried with a key that does not exist in a given row? The query must not error; it must return NULL for the missing key.
- What happens when the `status` column on `documents` receives a value outside the defined set (`pending`, `compiling`, `complete`, `failed`)? The schema must either enforce the constraint or document that validation is the responsibility of the application layer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The schema MUST define a `knowledge_bases` table with the following columns: `id` (UUID, primary key, auto-generated), `name` (text, not null), `slug` (text, unique, not null), `description` (text), `storage_container_path` (text), `git_versioning_enabled` (boolean, default true), `compilation_config` (semi-structured key-value store), `status` (text, not null), `created_at` (timestamp with timezone, default now), `updated_at` (timestamp with timezone, default now), `deleted_at` (timestamp with timezone, nullable).

- **FR-002**: The schema MUST define a `documents` table with the following columns: `id` (UUID, PK, auto-generated), `kb_id` (UUID, foreign key → `knowledge_bases.id`, not null), `source_type` (text, not null), `source_uri` (text), `original_filename` (text), `status` (text, not null), `failure_reason` (text, nullable), `pageindex_used` (boolean), `token_cost` (integer, nullable), `created_at`, `updated_at`, `deleted_at` (timestamptz as above).

- **FR-003**: The schema MUST define a `wiki_pages` table with the following columns: `id` (UUID, PK, auto-generated), `kb_id` (UUID, FK → `knowledge_bases.id`, not null), `page_type` (text, not null), `slug` (text, not null), `blob_path` (text), `entity_type` (text, nullable), `last_compiled_at` (timestamp with timezone, nullable), `created_at`, `updated_at`, `deleted_at` (timestamptz as above).

- **FR-004**: The schema MUST enforce a unique constraint on `knowledge_bases.slug`.

- **FR-005**: The schema MUST enforce a composite unique constraint on `(kb_id, slug)` in `wiki_pages`.

- **FR-006**: The schema MUST create indexes on all foreign key columns (`documents.kb_id`, `wiki_pages.kb_id`) to support efficient lookups.

- **FR-007**: All schema changes MUST be expressed as versioned, ordered migration files that can be applied incrementally; the migration tool MUST record which migrations have been applied so re-runs are safe.

- **FR-008**: A local development environment definition MUST be provided that spins up a Postgres instance (matching the target production version) without requiring any manual database installation on the developer's machine.

- **FR-009**: The local development environment MUST apply Phase 0 migrations automatically on first start, so the developer has a ready-to-use schema immediately after starting the environment.

- **FR-010**: A seed/fixture mechanism MUST be provided that creates at least one `knowledge_bases` record and at least two `documents` records with realistic test values, enabling local development and automated tests to run against a pre-populated database without manual SQL.

- **FR-011**: The seed/fixture mechanism MUST be runnable independently of the migration step, so tests can reset to a known state without re-running migrations.

- **FR-012**: A database connection/session factory MUST be provided as a reusable module that `compiler-worker` and `generator-api` can import. It MUST accept connection credentials from environment variables and MUST NOT embed hard-coded credentials.

- **FR-013**: The connection factory MUST support both local development (Docker Postgres) and production (Azure Database for PostgreSQL Flexible Server) targets using only configuration differences — no code changes.

- **FR-014**: The schema MUST be designed so that Phase 1 migrations can add `org_id` (nullable UUID) to `knowledge_bases` and `added_by` (nullable UUID) to `documents` without modifying or re-running the Phase 0 migrations.

- **FR-015**: No authentication, authorisation, or multi-tenancy tables or columns SHALL be created in this phase. Tables for `organizations`, `users`, `org_members`, `kb_access`, `api_tokens`, `audit_log`, `usage_ledger`, `sso_config`, `chat_sessions`, `chat_messages`, and `wiki_page_documents` are explicitly out of scope.

### Key Entities

- **KnowledgeBase**: The root container for a compilation project. Identified by a URL-safe slug. Holds configuration governing how documents are compiled (language, thresholds, entity types). Has a lifecycle status (`active` / `archived`). Maps to storage via `storage_container_path`. In Phase 0, there is no owning organisation — a single scratch instance suffices.

- **Document**: A source artefact ingested into a `KnowledgeBase`. Tracks where the file came from (`source_uri`), what format it is (`source_type`), its processing status (`pending` → `compiling` → `complete` / `failed`), and the computational cost of processing (`token_cost`). Flags whether the long-document PageIndex path was used (`pageindex_used`).

- **WikiPage**: A compiled output page generated from one or more documents in a `KnowledgeBase`. Identified by `slug` (unique within its KB). Typed by `page_type` to distinguish summaries, concepts, entity pages, indexes, and exploration pages. For entity pages, `entity_type` narrows the category. Points to its rendered file via `blob_path`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer with no prior setup can run two commands (start environment, apply migrations) and have a fully populated Phase 0 schema ready for use in under 5 minutes from a clean clone.

- **SC-002**: All three tables pass a schema validation check (column names, types, nullability, constraints, indexes) against the specification with zero discrepancies.

- **SC-003**: Migration runs are idempotent: running the migration command on an already-migrated database produces no errors and makes no schema changes, verified across 3 consecutive runs.

- **SC-004**: The seed/fixture command completes successfully and results in at least 1 queryable `knowledge_bases` row and at least 2 queryable `documents` rows within 10 seconds of execution.

- **SC-005**: The shared connection factory is successfully imported and used by a stub integration test for both `compiler-worker` and `generator-api`, confirming zero per-service connection boilerplate is required.

- **SC-006**: A stub Phase 1 migration adding `org_id` and `added_by` columns applies cleanly on top of the Phase 0 schema with no errors, confirming forward compatibility.

- **SC-007**: The `compiler-worker` service team confirms that the schema and session factory unblock their first integration test — the migration from "no database layer" to "queryable KB and document records" is completed within one sprint.

## Assumptions

- The target Postgres version for local development matches the version used in Azure Database for PostgreSQL Flexible Server (assumed to be Postgres 15 or later, consistent with Azure's current flexible server default; exact version to be confirmed in environment setup).
- The `compilation_config` column stores structured data as a JSON-compatible key-value store (`{ language, pageindex_threshold, entity_types, extra_headers }`) matching the shape consumed by the OpenKB engine. Schema validation of this JSON structure is the responsibility of the application layer, not the database.
- `status` columns on both `knowledge_bases` (`active`, `archived`) and `documents` (`pending`, `compiling`, `complete`, `failed`) are text fields without a database-level enum constraint in Phase 0; application-layer validation enforces the allowed values. This avoids migration friction if values are extended in Phase 1.
- Soft-delete (`deleted_at` nullable timestamptz) is the deletion strategy for all three tables. Hard deletes are not performed in Phase 0; queries filtering out soft-deleted rows are the responsibility of the application layer.
- The connection factory reads at minimum a database URL or individual host/port/user/password/dbname from environment variables. The exact variable names will be standardised across `compiler-worker` and `generator-api` during implementation (assumed: `DATABASE_URL` or equivalent).
- A single hardcoded scratch `knowledge_base` is sufficient for Phase 0 validation; no multi-tenancy or per-user isolation is needed.
- The repository is Python-based (consistent with the existing `openkb/` package and `pyproject.toml`), so the migration tooling and session factory will be Python-native. Specific library choices (SQLAlchemy, Alembic, asyncpg, etc.) are implementation decisions for the planning phase.
- SSL/TLS for the database connection in production (required by Azure Database for PostgreSQL) is handled via connection string configuration rather than code-level certificate management.

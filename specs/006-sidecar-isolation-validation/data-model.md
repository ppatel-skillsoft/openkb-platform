# Data Model: Phase 0 Sidecar Isolation Validation

**Feature**: 006-sidecar-isolation-validation  
**Phase**: 1 — Design & Contracts  
**Date**: 2026-06-21

> This spec produces no new database tables or service entities. The data model below describes the **test-harness domain objects** — the in-memory and fixture-file entities the test harness creates, inspects, and asserts against. These are not stored in Postgres; they exist as Python dataclasses, fixture files, and runtime state within the test process.

---

## Entity 1: KB Fixture

A self-contained, minimal knowledge base used exclusively for isolation testing. Created once per test session, seeded into Postgres and Azurite, and destroyed at session teardown.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid.UUID` | Stable fixture UUID — hardcoded per fixture so assertions are reproducible across runs |
| `slug` | `str` | URL-safe identifier (`kb-a` or `kb-b`) |
| `name` | `str` | Human-readable name (`"Isolation Test KB-A: Astronomy"`, `"Isolation Test KB-B: Botany"`) |
| `storage_container_path` | `str` | Blob path prefix where compiled wiki pages are stored (`kb-{id}/wiki/`) |
| `source_document_path` | `Path` | Path to the local fixture markdown file relative to `tests/isolation/fixtures/` |
| `topic_keywords` | `frozenset[str]` | Distinguishing terms used in citation assertions (e.g., `{"main sequence", "red giant"}` for KB-A) |

**Postgres row** (seeded into `knowledge_bases` table):

```python
KB_A = KBFixture(
    id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
    slug="kb-a",
    name="Isolation Test KB-A: Astronomy",
    storage_container_path="kb-aaaaaaaa-0000-0000-0000-000000000001/wiki",
    source_document_path=Path("fixtures/kb_a/astronomy-intro.md"),
    topic_keywords=frozenset({"main sequence", "red giant", "Hertzsprung-Russell", "planetary nebula"}),
)

KB_B = KBFixture(
    id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"),
    slug="kb-b",
    name="Isolation Test KB-B: Botany",
    storage_container_path="kb-bbbbbbbb-0000-0000-0000-000000000002/wiki",
    source_document_path=Path("fixtures/kb_b/botany-intro.md"),
    topic_keywords=frozenset({"chloroplast", "photosynthesis", "stomata", "xylem", "phloem"}),
)
```

**State transitions**: KB fixtures are seeded with `status = 'active'` in `knowledge_bases`. Corresponding `documents` rows are seeded with `status = 'complete'` (pre-compiled; the isolation tests assert on the isolation model, not on compilation correctness — compilation output is pre-seeded into Azurite).

**Validation rules**:
- `id` is hardcoded (not auto-generated) so fixture blobs at known paths survive test session restarts during debugging
- `topic_keywords` must be disjoint between KB-A and KB-B — verified in `conftest.py` at session start with `assert KB_A.topic_keywords.isdisjoint(KB_B.topic_keywords)`
- `storage_container_path` follows the `kb-{id}/wiki/` convention from spec 002's blob storage paths contract

---

## Entity 2: Isolation Test Scenario

One of the five named isolation properties under validation. Not stored anywhere — exists as a pytest test module with a corresponding result.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Scenario identifier (maps 1:1 to a test file name) |
| `priority` | `Literal["P1", "P2"]` | From spec: P1 = must pass for Phase 0 sign-off; P2 = strongly recommended |
| `isolation_property` | `str` | Human description of what property is under test |
| `fixture_requirement` | `str` | What KB fixtures and infrastructure state must be present before the scenario runs |
| `assertions` | `list[str]` | Ordered list of programmatic assertions (not prose — these map to `assert` statements) |
| `pass_condition` | `str` | Unambiguous definition of what constitutes a pass |
| `fail_evidence` | `str` | What evidence the test collects on failure to enable diagnosis |

| Scenario | File | Priority | Property |
|----------|------|----------|---------|
| Scratch Directory Isolation | `test_scratch_directory_isolation.py` | P1 | No shared path prefix between concurrent KB-A and KB-B scratch dirs |
| Port Isolation | `test_port_isolation.py` | P1 | Distinct ports; KB-A HTTP → KB-A response only |
| Process State Isolation | `test_process_state_isolation.py` | P2 | KB-B sidecar has zero access to KB-A artefacts after KB-A teardown |
| Sequential Reuse Safety | `test_sequential_reuse_safety.py` | P2 | Prior sidecar fully dead; prior scratch dir fully deleted before KB-B starts |
| Concurrent Query Isolation | `test_concurrent_query_isolation.py` | P2 | Concurrent queries return only own-KB citations |

---

## Entity 3: Sidecar Instance

A running instance of the upstream OpenKB sidecar process, managed by the compiler-worker or generator-api. The test harness does not start sidecars directly — it enqueues jobs and observes the resulting sidecar lifecycle through the shared scratch volume and psutil.

| Field | Type | Description |
|-------|------|-------------|
| `pid` | `int` | OS process ID; used for `psutil` assertions |
| `bound_port` | `int` | Port the sidecar's HTTP server is listening on (OS-assigned, 1024–65535) |
| `scratch_dir` | `Path` | Absolute path to this sidecar's exclusive working directory on the shared volume |
| `kb_id` | `uuid.UUID` | The knowledge base this sidecar serves |
| `lifecycle_state` | `Literal["starting", "running", "torn_down"]` | Current state as observed by the harness |

**Lifecycle state transitions** (as observed, not managed, by the test harness):

```
starting ──(HTTP /health responds 200)──► running
running  ──(job complete; worker SIGTERM)──► torn_down
running  ──(timeout; worker SIGKILL)──► torn_down
```

**Invariants** (asserted by the harness):
- Two concurrent `SidecarInstance` objects must have `bound_port` values with no overlap: `assert sidecar_a.bound_port != sidecar_b.bound_port`
- Two concurrent `SidecarInstance` objects must have `scratch_dir` values that share no path prefix under the scratch root: `assert not sidecar_a.scratch_dir.is_relative_to(sidecar_b.scratch_dir)` and vice versa
- A `torn_down` sidecar must have `psutil.pid_exists(pid) == False` or `psutil.Process(pid).status() == psutil.STATUS_ZOMBIE` followed by its absence after OS reaping

---

## Entity 4: Scratch Directory

A temporary working area allocated exclusively to one sidecar instance for one job or query request. Exists on the `compiler_scratch` named Docker volume.

| Field | Type | Description |
|-------|------|-------------|
| `path` | `Path` | Absolute path within the shared scratch volume (e.g., `/scratch/{kb_id}/{job_id}/`) |
| `kb_id` | `uuid.UUID` | The knowledge base this directory belongs to |
| `job_id` | `str` | Unique job identifier (UUID or similar); forms part of the path |
| `contents_at_t0` | `set[Path]` | Snapshot of file paths present at mid-run assertion time (Scenario 1) |
| `exists_after_teardown` | `bool` | Whether the directory still exists after the job completes; MUST be `False` |

**Naming convention** (from spec 002 sidecar spawn contract):
```
/scratch/{kb_id}/{job_id}/
    raw/                    # Downloaded source document(s)
    wiki/                   # Sidecar's working wiki tree
```

**Validation rules**:
- `path` for KB-A and KB-B jobs must not be equal and must not be a prefix of each other
- For any completed job, `path` must not exist on the volume: `assert not path.exists()`
- `contents_at_t0` for KB-A must contain no files whose names match KB-B fixture document names, and vice versa

---

## Entity 5: Wiki Blob Seed

Pre-compiled wiki page blobs uploaded to Azurite during `conftest.py` session setup. These simulate the output of the compiler-worker so that generator-api query tests (Scenario 5) do not depend on a successful compilation run.

| Field | Type | Description |
|-------|------|-------------|
| `container_name` | `str` | Azurite container name (convention: `openkb` for all KBs) |
| `blob_path` | `str` | Full blob path under the KB's `storage_container_path` (e.g., `kb-{id}/wiki/summary.md`) |
| `content` | `bytes` | Minimal valid wiki markdown content identifying the KB |
| `kb_id` | `uuid.UUID` | The KB this blob belongs to |

**Seeding strategy**: For each KB fixture, upload a minimal `summary.md` and one `concepts/` page containing the KB's `topic_keywords` in the text body. This ensures:
1. generator-api can locate at least one `wiki_pages` row with `status = 'complete'` (from Postgres seed)
2. The sidecar, when pointed at the downloaded wiki tree, can answer a query about the KB's topic
3. Cross-contamination is detectable: KB-B's wiki contains only botany terms; KB-A's wiki contains only astronomy terms

---

## Entity relationships

```
KBFixture ──(1:1)──► knowledge_bases row (Postgres)
KBFixture ──(1:N)──► documents rows (Postgres, status=complete)
KBFixture ──(1:N)──► WikiBlobSeed entries (Azurite blobs)
KBFixture ──(runtime: 1:1)──► SidecarInstance (per job or query)
SidecarInstance ──(1:1)──► ScratchDirectory
IsolationTestScenario ──(1:2)──► KBFixture (KB-A and KB-B are both required for every scenario)
```

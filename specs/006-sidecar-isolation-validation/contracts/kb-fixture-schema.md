# Contract: KB Fixture Schema

**Owner**: spec 006-sidecar-isolation-validation  
**Consumers**: `tests/isolation/conftest.py`, `tests/isolation/helpers/blob_helpers.py`, RUNBOOK.md  
**Date**: 2026-06-21

---

## Overview

This document defines the exact structure of the two minimal knowledge-base fixtures (KB-A and KB-B) used by the isolation test suite. Both fixtures are created during `conftest.py` session setup and destroyed during session teardown. They exist in three places simultaneously:

1. **Postgres** — `knowledge_bases` and `documents` rows
2. **Azurite** — pre-compiled wiki blob pages under `kb-{id}/wiki/`
3. **Local test fixture files** — source markdown documents at `tests/isolation/fixtures/`

---

## KB-A: Astronomy Knowledge Base

### Postgres rows

**`knowledge_bases` row**:
```json
{
  "id":                     "aaaaaaaa-0000-0000-0000-000000000001",
  "name":                   "Isolation Test KB-A: Astronomy",
  "slug":                   "kb-a",
  "description":            "Test fixture for sidecar isolation validation — astronomy content",
  "storage_container_path": "kb-aaaaaaaa-0000-0000-0000-000000000001/wiki",
  "git_versioning_enabled": false,
  "compilation_config":     {"language": "en"},
  "status":                 "active",
  "created_at":             "2026-06-21T00:00:00Z",
  "updated_at":             "2026-06-21T00:00:00Z",
  "deleted_at":             null
}
```

**`documents` row**:
```json
{
  "id":                "aaaaaaaa-0001-0000-0000-000000000001",
  "kb_id":             "aaaaaaaa-0000-0000-0000-000000000001",
  "source_type":       "markdown",
  "source_uri":        "azurite://openkb/kb-aaaaaaaa-0000-0000-0000-000000000001/raw/astronomy-intro.md",
  "original_filename": "astronomy-intro.md",
  "status":            "complete",
  "failure_reason":    null,
  "pageindex_used":    false,
  "token_cost":        120,
  "created_at":        "2026-06-21T00:00:00Z",
  "updated_at":        "2026-06-21T00:00:00Z",
  "deleted_at":        null
}
```

### Azurite blobs

Container: `openkb`

| Blob path | Content summary |
|-----------|----------------|
| `kb-aaaaaaaa-0000-0000-0000-000000000001/wiki/summary.md` | Summary of astronomy intro document; contains topic keywords |
| `kb-aaaaaaaa-0000-0000-0000-000000000001/wiki/concepts/stellar-classification.md` | Concept page; body contains "main sequence", "red giant", "Hertzsprung-Russell" |
| `kb-aaaaaaaa-0000-0000-0000-000000000001/raw/astronomy-intro.md` | Source document (copy of fixture file) |

**`wiki/summary.md` content** (verbatim — pinned for reproducibility):
```markdown
# Astronomy Introduction — Summary

This document introduces stellar classification and planetary formation.
Key topics: main sequence stars, red giants, the Hertzsprung-Russell diagram,
planetary nebula, and stellar evolution cycles.

Source: astronomy-intro.md
```

**`wiki/concepts/stellar-classification.md` content**:
```markdown
# Stellar Classification

Stars are classified by temperature and luminosity on the Hertzsprung-Russell diagram.
Main sequence stars fuse hydrogen in their cores. Red giants form when main sequence
stars exhaust their hydrogen supply and expand. A planetary nebula is the expelled
outer shell of a red giant after it collapses to a white dwarf.

Source: astronomy-intro.md
```

### `wiki_pages` rows (Postgres)

```json
[
  {
    "id":              "aaaaaaaa-0002-0000-0000-000000000001",
    "kb_id":           "aaaaaaaa-0000-0000-0000-000000000001",
    "page_type":       "summary",
    "slug":            "summary",
    "blob_path":       "kb-aaaaaaaa-0000-0000-0000-000000000001/wiki/summary.md",
    "entity_type":     null,
    "last_compiled_at":"2026-06-21T00:00:00Z"
  },
  {
    "id":              "aaaaaaaa-0003-0000-0000-000000000001",
    "kb_id":           "aaaaaaaa-0000-0000-0000-000000000001",
    "page_type":       "concept",
    "slug":            "stellar-classification",
    "blob_path":       "kb-aaaaaaaa-0000-0000-0000-000000000001/wiki/concepts/stellar-classification.md",
    "entity_type":     null,
    "last_compiled_at":"2026-06-21T00:00:00Z"
  }
]
```

### Source fixture file

**Path**: `tests/isolation/fixtures/kb_a/astronomy-intro.md`  
**Purpose**: Used as the source document when Scenario 1 (scratch dir isolation) triggers a real compilation job via the compiler-worker. Pre-compiled wiki blobs are used for Scenarios 3 and 5.

**Topic keywords** (must not appear in KB-B fixture content):
`main sequence`, `red giant`, `Hertzsprung-Russell`, `planetary nebula`, `stellar`

---

## KB-B: Botany Knowledge Base

### Postgres rows

**`knowledge_bases` row**:
```json
{
  "id":                     "bbbbbbbb-0000-0000-0000-000000000002",
  "name":                   "Isolation Test KB-B: Botany",
  "slug":                   "kb-b",
  "description":            "Test fixture for sidecar isolation validation — botany content",
  "storage_container_path": "kb-bbbbbbbb-0000-0000-0000-000000000002/wiki",
  "git_versioning_enabled": false,
  "compilation_config":     {"language": "en"},
  "status":                 "active",
  "created_at":             "2026-06-21T00:00:00Z",
  "updated_at":             "2026-06-21T00:00:00Z",
  "deleted_at":             null
}
```

**`documents` row**:
```json
{
  "id":                "bbbbbbbb-0001-0000-0000-000000000002",
  "kb_id":             "bbbbbbbb-0000-0000-0000-000000000002",
  "source_type":       "markdown",
  "source_uri":        "azurite://openkb/kb-bbbbbbbb-0000-0000-0000-000000000002/raw/botany-intro.md",
  "original_filename": "botany-intro.md",
  "status":            "complete",
  "failure_reason":    null,
  "pageindex_used":    false,
  "token_cost":        115,
  "created_at":        "2026-06-21T00:00:00Z",
  "updated_at":        "2026-06-21T00:00:00Z",
  "deleted_at":        null
}
```

### Azurite blobs

Container: `openkb`

| Blob path | Content summary |
|-----------|----------------|
| `kb-bbbbbbbb-0000-0000-0000-000000000002/wiki/summary.md` | Summary of botany intro document; contains topic keywords |
| `kb-bbbbbbbb-0000-0000-0000-000000000002/wiki/concepts/photosynthesis.md` | Concept page; body contains "chloroplast", "photosynthesis", "stomata" |
| `kb-bbbbbbbb-0000-0000-0000-000000000002/raw/botany-intro.md` | Source document (copy of fixture file) |

**`wiki/summary.md` content** (verbatim — pinned for reproducibility):
```markdown
# Botany Introduction — Summary

This document introduces plant cell biology and energy production.
Key topics: chloroplasts, photosynthesis, stomata, xylem and phloem transport,
and the Calvin cycle.

Source: botany-intro.md
```

**`wiki/concepts/photosynthesis.md` content**:
```markdown
# Photosynthesis

Photosynthesis is the process by which plants convert light energy into chemical energy.
Chloroplasts contain chlorophyll, which absorbs sunlight. Carbon dioxide enters leaves
through stomata. Water and nutrients are transported via xylem; sugars are distributed
via phloem. The Calvin cycle converts CO2 into glucose in the chloroplast stroma.

Source: botany-intro.md
```

### `wiki_pages` rows (Postgres)

```json
[
  {
    "id":              "bbbbbbbb-0002-0000-0000-000000000002",
    "kb_id":           "bbbbbbbb-0000-0000-0000-000000000002",
    "page_type":       "summary",
    "slug":            "summary",
    "blob_path":       "kb-bbbbbbbb-0000-0000-0000-000000000002/wiki/summary.md",
    "entity_type":     null,
    "last_compiled_at":"2026-06-21T00:00:00Z"
  },
  {
    "id":              "bbbbbbbb-0003-0000-0000-000000000002",
    "kb_id":           "bbbbbbbb-0000-0000-0000-000000000002",
    "page_type":       "concept",
    "slug":            "photosynthesis",
    "blob_path":       "kb-bbbbbbbb-0000-0000-0000-000000000002/wiki/concepts/photosynthesis.md",
    "entity_type":     null,
    "last_compiled_at":"2026-06-21T00:00:00Z"
  }
]
```

### Source fixture file

**Path**: `tests/isolation/fixtures/kb_b/botany-intro.md`  
**Purpose**: Used as the source document when Scenario 1 triggers a real compilation job.

**Topic keywords** (must not appear in KB-A fixture content):
`chloroplast`, `photosynthesis`, `stomata`, `xylem`, `phloem`, `Calvin cycle`

---

## Fixture invariants

The `conftest.py` session fixture MUST assert these invariants before any test runs:

```python
# 1. Topic keyword disjointness — detects fixture drift
assert KB_A.topic_keywords.isdisjoint(KB_B.topic_keywords), \
    "KB fixture topic keywords must be disjoint for cross-contamination to be detectable"

# 2. Storage path uniqueness — detects accidental path collision
assert KB_A.storage_container_path != KB_B.storage_container_path

# 3. Slug uniqueness — detects accidental slug collision
assert KB_A.slug != KB_B.slug

# 4. Filename non-overlap (same filename in different KBs is an intentional edge case — 
#    files share the suffix "-intro.md" but have different base names)
assert KB_A.source_document_path.name != KB_B.source_document_path.name, \
    "Source document filenames differ between KB-A and KB-B (edge case: same suffix is intentional)"
```

---

## Fixture teardown

At session teardown, `conftest.py` MUST:
1. Delete all `wiki_pages` rows for KB-A and KB-B from Postgres
2. Delete all `documents` rows for KB-A and KB-B from Postgres
3. Delete all `knowledge_bases` rows for KB-A and KB-B from Postgres
4. Delete all blobs under `kb-aaaaaaaa-0000-0000-0000-000000000001/` from Azurite
5. Delete all blobs under `kb-bbbbbbbb-0000-0000-0000-000000000002/` from Azurite

Teardown is idempotent — it uses `DELETE WHERE id = ...` and `DELETE IF EXISTS` patterns so a partial teardown from a crashed session does not block a subsequent run (SC-005).

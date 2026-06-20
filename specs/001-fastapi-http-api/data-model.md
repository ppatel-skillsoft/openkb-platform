# Data Model: FastAPI HTTP API Layer

**Phase**: 1 — Design & Contracts
**Feature**: `001-fastapi-http-api`
**Date**: 2026-06-19

---

## 1. StorageBackend Abstraction (`openkb/storage/base.py`)

Abstract base class. All methods are async. Both implementations must satisfy
this contract without exception.

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator

class StorageBackend(ABC):
    """Async I/O and locking interface for a single KB instance."""

    # --- Read ---

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """Read file at `path` (relative to KB root). Raises FileNotFoundError."""

    async def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return (await self.read_bytes(path)).decode(encoding)

    # --- Write ---

    @abstractmethod
    async def write_bytes(self, path: str, content: bytes) -> None:
        """Atomically write `content` to `path`. Creates parent dirs."""

    async def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        await self.write_bytes(path, content.encode(encoding))

    # --- Metadata ---

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return True if `path` exists."""

    @abstractmethod
    async def get_mtime(self, path: str) -> float | None:
        """Return last-modified POSIX timestamp, or None if not found."""

    # --- Listing ---

    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[str]:
        """Return relative paths of all files under `prefix/`."""

    # --- Delete ---

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete file at `path`. No-op if already absent."""

    # --- Locking ---

    @asynccontextmanager
    @abstractmethod
    async def lock(
        self,
        resource: str = "ingest",
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[None]:
        """Acquire exclusive write lock. Raises LockTimeoutError on timeout."""
        ...  # pragma: no cover
```

---

## 2. `LocalStorageBackend` (`openkb/storage/local.py`)

Wraps `pathlib.Path`. I/O runs in `asyncio.to_thread` to avoid blocking the
event loop. Locking delegates to the existing `kb_ingest_lock` from
`openkb.locks`.

### Key fields

| Attribute | Type | Description |
|---|---|---|
| `kb_dir` | `Path` | Root directory of the KB instance |

### Locking

Uses `asyncio.to_thread` to run the synchronous `portalocker`-backed
`kb_ingest_lock(openkb_dir)` context manager without blocking the event loop.

### Bridge to compiler layer

Exposes `kb_dir` as a public property so service functions can pass it to the
path-based compiler and query functions.

---

## 3. `AzureBlobStorageBackend` (`openkb/storage/azure_blob.py`)

Wraps `azure.storage.blob.aio.BlobServiceClient`. Paths are stored as
`<kb_name>/<relative_path>` blob names within a single container.

### Key fields

| Attribute | Type | Description |
|---|---|---|
| `_connection_string` | `str` | Azure Storage connection string (from env) |
| `_container_name` | `str` | Blob container (from `AZURE_KB_CONTAINER`) |
| `_kb_name` | `str` | KB slug — prefix for all blobs |
| `_client` | `BlobServiceClient` | Async SDK client (initialised lazily) |

### Locking

Uses `BlobLeaseClient.acquire(lease_duration=60)` on a dedicated lock blob
(`<kb_name>/.openkb/ingest.lock`). Polls every 1 s until timeout. Raises
`LockTimeoutError` if not acquired within `timeout` seconds.

### Bridge to compiler layer

`local_working_dir()` — an async context manager that:
1. Creates a `tempfile.TemporaryDirectory`.
2. Downloads all blobs under `<kb_name>/` to the temp dir.
3. Yields the temp dir `Path`.
4. On exit, uploads all new / changed files from the temp dir back to blob.
Service functions use this context manager around any call to the compiler or
query agents that require a local `kb_dir: Path`.

---

## 4. Service Result Types (`openkb/services/`)

Plain Python dataclasses. These are the return types of the five service
functions. They are NOT Pydantic models — the Pydantic response models in
`openkb/api/models.py` are constructed from them in the route handlers.

```python
# openkb/services/__init__.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class KBInitResult:
    status: Literal["created", "exists"]
    kb_name: str
    message: str

@dataclass
class KBAddResult:
    status: Literal["added", "skipped", "failed"]
    doc_name: str | None
    message: str

@dataclass
class KBQueryResult:
    answer: str
    saved_to: str | None   # blob path or local path if save=True

@dataclass
class DocumentEntry:
    name: str           # original filename
    doc_name: str       # slug (collision-resistant)
    type: str           # display type: "short" | "pageindex" | raw ext

@dataclass
class KBListResult:
    documents: list[DocumentEntry]
    summaries: list[str]    # sorted stems
    concepts: list[str]
    entities: list[str]
    reports: list[str]

@dataclass
class KBStatusResult:
    kb_name: str
    total_indexed: int
    last_compile: str | None    # ISO-8601 UTC or None
    last_lint: str | None       # ISO-8601 UTC or None
    directory_counts: dict[str, int]   # subdir name → file count
```

---

## 5. Custom Exceptions (`openkb/services/__init__.py`)

All service functions raise these; neither FastAPI nor Click semantics leak
into the service layer.

| Exception | Raised when | Maps to |
|---|---|---|
| `KBNotFoundError(kb_name)` | KB has no `.openkb/config.yaml` | HTTP 404 |
| `KBAlreadyExistsError(kb_name)` | `init` called on an existing KB | HTTP 409 |
| `UnsupportedDocumentError(ext, supported)` | File extension not in `SUPPORTED_EXTENSIONS` | HTTP 422 |
| `URLFetchError(url, detail)` | URL is unreachable / returns non-200 | HTTP 422 |
| `LLMError(detail)` | LiteLLM / LLM API failure | HTTP 502 |
| `LockTimeoutError(resource)` | Azure Blob Lease not acquired within timeout | HTTP 503 |

---

## 6. API Request / Response Models (`openkb/api/models.py`)

All Pydantic v2 models. Field validators mirror `_coerce_model` /
`_coerce_language` from `cli.py`.

### Request models

#### `KBInitRequest`
| Field | Type | Constraints | Description |
|---|---|---|---|
| `kb_name` | `str` | pattern `^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$\|^[a-z0-9]$`, max 64 chars | KB identifier slug |
| `model` | `str \| None` | max 100 chars, no control chars, default `None` | LLM model string |
| `language` | `str \| None` | max 50 chars, no control chars, default `None` | Wiki output language |

#### `KBAddRequest`
| Field | Type | Constraints | Description |
|---|---|---|---|
| `kb_name` | `str` | same as above | Target KB |
| `source` | `str` | non-blank | File path accessible to server, or `http(s)://` URL |

#### `KBQueryRequest`
| Field | Type | Constraints | Description |
|---|---|---|---|
| `kb_name` | `str` | same as above | Target KB |
| `question` | `str` | min length 1, stripped | Natural language question |
| `save` | `bool` | default `False` | Save answer to `wiki/explorations/` |

#### Query parameters (GET endpoints — resolved via `Annotated[str, Query(...)]`)
| Parameter | Endpoint | Constraints |
|---|---|---|
| `kb_name` | `GET /kb/list`, `GET /kb/status` | same slug pattern as request models |

---

### Response models

#### `KBInitResponse`
| Field | Type | Description |
|---|---|---|
| `kb_name` | `str` | The KB slug |
| `status` | `Literal["created", "exists"]` | Outcome |
| `message` | `str` | Human-readable, actionable |

#### `KBAddResponse`
| Field | Type | Description |
|---|---|---|
| `status` | `Literal["added", "skipped", "failed"]` | Outcome |
| `doc_name` | `str \| None` | Slug of the ingested document |
| `message` | `str` | Human-readable |

#### `KBQueryResponse`
| Field | Type | Description |
|---|---|---|
| `answer` | `str` | LLM answer (may be empty string for empty KB) |
| `saved_to` | `str \| None` | Path/blob where answer was saved; `None` if `save=False` |

#### `KBListResponse`
| Field | Type | Description |
|---|---|---|
| `documents` | `list[DocumentItem]` | Indexed documents |
| `summaries` | `list[str]` | Sorted summary stems |
| `concepts` | `list[str]` | Sorted concept stems |
| `entities` | `list[str]` | Sorted entity stems |
| `reports` | `list[str]` | Sorted report filenames |

`DocumentItem`:
| Field | Type | Description |
|---|---|---|
| `name` | `str` | Original filename |
| `doc_name` | `str` | Slug |
| `type` | `str` | Display type: `"short"` \| `"pageindex"` \| raw ext |

#### `KBStatusResponse`
| Field | Type | Description |
|---|---|---|
| `kb_name` | `str` | KB slug |
| `total_indexed` | `int` | Number of registry entries |
| `last_compile` | `str \| None` | ISO-8601 UTC timestamp of newest compiled page, or `null` |
| `last_lint` | `str \| None` | ISO-8601 UTC timestamp of newest report, or `null` |
| `directory_counts` | `dict[str, int]` | `{"summaries": 3, "concepts": 5, ...}` |

#### `ErrorResponse`
| Field | Type | Description |
|---|---|---|
| `detail` | `str` | Human-readable, actionable error message |

---

## 7. FastAPI Application (`openkb/api/app.py`)

```python
def create_app(*, base_dir: Path | None = None) -> FastAPI:
    """Factory function. `base_dir` overrides OPENKB_BASE_DIR (used in tests)."""
    app = FastAPI(title="OpenKB API", version=__version__)
    app.include_router(kb_router, prefix="/kb")
    # Exception handlers: KBNotFoundError → 404, KBAlreadyExistsError → 409,
    #   LockTimeoutError → 503, LLMError → 502, UnsupportedDocumentError → 422
    return app
```

### Lifespan (startup checks)

- Validates `OPENKB_STORAGE_BACKEND` is one of `{"local", "azure"}`.
- For `azure`: validates `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_KB_CONTAINER` are set.
- For `local`: validates `OPENKB_BASE_DIR` is set and is a directory.
- Logs backend choice at INFO level.

---

## 8. Dependency: `get_backend` (`openkb/api/deps.py`)

Resolves a `StorageBackend` instance per request based on `kb_name` path/query
parameter and the process-level `OPENKB_STORAGE_BACKEND` setting.

```python
async def get_backend(
    kb_name: str,          # injected by each route as a query param or body field
    settings: Settings = Depends(get_settings),
) -> StorageBackend:
    if settings.storage_backend == "azure":
        return AzureBlobStorageBackend(
            connection_string=settings.azure_storage_connection_string,
            container=settings.azure_kb_container,
            kb_name=kb_name,
        )
    return LocalStorageBackend(
        kb_dir=settings.openkb_base_dir / kb_name,
    )
```

---

## 9. Entity Relationships

```
StorageBackend (ABC)
    ├── LocalStorageBackend
    │     └── uses: pathlib.Path, portalocker (via asyncio.to_thread)
    │     └── exposes: .kb_dir → Path  (bridge to compiler layer)
    └── AzureBlobStorageBackend
          └── uses: BlobServiceClient (async), BlobLeaseClient
          └── exposes: .local_working_dir() → AsyncIterator[Path]

ServiceFunctions
    ├── service_init_kb(backend: StorageBackend, ...)        → KBInitResult
    ├── service_add_document(backend: StorageBackend, ...)   → KBAddResult
    ├── service_query_kb(backend: StorageBackend, ...)       → KBQueryResult
    ├── service_list_kb(backend: StorageBackend, ...)        → KBListResult
    └── service_status_kb(backend: StorageBackend, ...)      → KBStatusResult

APIRoutes (openkb/api/routes/kb.py)
    ├── POST /kb/init    → calls service_init_kb
    ├── POST /kb/add     → calls service_add_document
    ├── POST /kb/query   → calls service_query_kb
    ├── GET  /kb/list    → calls service_list_kb
    └── GET  /kb/status  → calls service_status_kb

CLI Commands (openkb/cli.py)
    ├── openkb init      → calls service_init_kb
    ├── openkb add       → calls service_add_document (via add_single_file wrapper)
    ├── openkb query     → calls service_query_kb
    ├── openkb list      → calls service_list_kb + click.echo
    ├── openkb status    → calls service_status_kb + click.echo
    └── openkb serve     → launches uvicorn with create_app()
```

---

## 10. State Transitions: KB Lifecycle

```
[Not initialised]
        │
        ▼  POST /kb/init (or openkb init)
  [Initialised: empty]
        │
        ▼  POST /kb/add (or openkb add)
  [Initialised: has documents]
        │  (loop: add more documents)
        │
        ▼  POST /kb/query (or openkb query)
  [Queried]   ←──────────────────────────┐
        │                               │
        ▼  POST /kb/add                 │
  [Growing]   ───────────────────────────┘

  [Any state where KB exists]
        │
        ▼  GET /kb/list  /  GET /kb/status
  [Read-only introspection — no state change]
```

---

## 11. Validation Rules (shared between CLI and API)

| Field | Rule | Source |
|---|---|---|
| `kb_name` | `[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]` or single `[a-z0-9]`; max 64 chars | FR-001; Key Entities |
| `model` | max 100 chars; no `\n \r \t` chars | `_coerce_model` in `cli.py:510` |
| `language` | max 50 chars; no `\n \r \t` chars | `_coerce_language` in `cli.py:481` |
| `question` | min 1 char after strip | FR-003 |
| `source` | non-blank string; validated as local path or `http(s)://` URL | FR-002 |

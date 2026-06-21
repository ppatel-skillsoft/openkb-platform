# Research: FastAPI HTTP API Layer

**Phase**: 0 — Outline & Research
**Feature**: `001-fastapi-http-api`
**Date**: 2026-06-19

---

## R-001 — FastAPI async route handler best practices

**Decision**: Route handlers are thin async functions that delegate all work to
service functions injected as FastAPI `Depends()` dependencies. No business
logic inside the handler body.

**Rationale**: FastAPI's dependency injection system is the idiomatic way to
inject backend instances and avoid coupling route handlers to concrete
implementations. Async handlers allow uvicorn to multiplex requests without
blocking the event loop during I/O.

**Pattern**:
```python
@router.post("/kb/add", response_model=KBAddResponse)
async def add_document(
    body: KBAddRequest,
    backend: StorageBackend = Depends(get_backend),
) -> KBAddResponse:
    return await service_add_document(backend, body.source)
```

**Alternatives considered**: Putting logic directly in routes (rejected —
violates FR-008 and Constitution §II); synchronous handlers with
`run_in_executor` (rejected — no benefit over native async, complicates error
propagation).

---

## R-002 — Pydantic v2 validation for model/language inputs

**Decision**: Pydantic v2 `field_validator` (mode `"before"`) replicates the
`_coerce_model` / `_coerce_language` rules from `cli.py` inside the request
models. The validator strips whitespace, rejects control characters, and
enforces max-length. FastAPI then returns HTTP 422 automatically on failure.

**Rationale**: Pydantic v2 is a hard requirement of `fastapi==0.137.2`. The
field validators provide the same safeguards as the CLI's Click callbacks at
the HTTP boundary, satisfying FR-007.

**Key constants (mirrored from `cli.py`)**:
```python
_MODEL_MAX_LEN    = 100  # characters
_LANGUAGE_MAX_LEN =  50  # characters
_CONTROL_CHARS    = frozenset("\n\r\t")
```

**Pattern**:
```python
class KBInitRequest(BaseModel):
    kb_name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$")
    model: str | None = None
    language: str | None = None

    @field_validator("model", "language", mode="before")
    @classmethod
    def _strip_and_validate(cls, v: str | None, info: FieldValidationInfo) -> str | None:
        # mirrors _coerce_model / _coerce_language
        ...
```

**Alternatives considered**: Separate validation module (overkill for two
fields); `__validators__` (deprecated in Pydantic v2).

---

## R-003 — StorageBackend abstraction design

**Decision**: An abstract base class (`StorageBackend`) with seven methods:
`read_bytes`, `write_bytes`, `delete`, `exists`, `list_prefix`, `get_mtime`,
and an async context-manager `lock`. Two concrete implementations:
`LocalStorageBackend` (wraps `pathlib.Path` + `portalocker` via
`asyncio.to_thread`) and `AzureBlobStorageBackend` (wraps async
`BlobServiceClient` + Blob Lease API).

**Rationale**: The ABC forces both backends to satisfy the same contract. The
service layer calls only ABC methods, so no `pathlib.Path` or `os` calls appear
in service code (FR-014). The `lock` context manager is the only coordination
primitive; callers do not care whether it's `portalocker` or a Blob Lease.

**Bridge to compiler/query layer**: The existing compiler functions
(`compile_short_doc`, `compile_long_doc`, `run_query`) take `kb_dir: Path`
because they are in the foundation layer and pre-date this feature. The
service layer bridges the gap:

- `LocalStorageBackend` exposes a `.kb_dir` property returning the root `Path`.
  Service functions pass it directly to compiler calls.

- `AzureBlobStorageBackend` exposes an async context manager
  `.local_working_dir()` that downloads the KB prefix to a `tempfile.TemporaryDirectory`,
  yields the local `Path`, and on exit uploads changed files back to blob. The
  service layer uses this context manager around every compiler call.

This keeps the compiler and query layers unchanged while satisfying FR-014 for
shared service code (the service functions themselves only call StorageBackend
methods; the local Path they pass into the compiler is obtained from the
backend, not constructed independently).

**Interface**:
```python
class StorageBackend(ABC):
    @abstractmethod
    async def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    async def write_bytes(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[str]: ...

    @abstractmethod
    async def get_mtime(self, path: str) -> float | None: ...

    @abstractmethod
    @asynccontextmanager
    async def lock(
        self, resource: str, *, timeout: float = 30.0
    ) -> AsyncIterator[None]: ...
```

**Alternatives considered**: Making the compiler functions backend-aware
(rejected — too large a change, breaks foundation-layer purity); using a
virtual filesystem library like `fsspec` (rejected — adds a heavy dependency
and the abstraction surface is small enough to own).

---

## R-004 — Azure Blob Lease for distributed locking

**Decision**: Use `BlobLeaseClient.acquire(lease_duration=60)` on a dedicated
lock blob (`<kb_name>/.openkb/ingest.lock`) to serialise write operations
across multiple API instances. If the lease cannot be acquired within the
configured timeout (default: 30 s), raise `LockTimeoutError` which the route
handler converts to HTTP 503.

**Rationale**: Azure Blob Lease is the canonical distributed lock primitive for
Blob Storage. It's atomic, server-enforced, and survives process crashes (leases
expire automatically after `lease_duration` seconds). This satisfies FR-013 and
SC-005.

**Pattern**:
```python
@asynccontextmanager
async def lock(self, resource: str, *, timeout: float = 30.0) -> AsyncIterator[None]:
    blob_client = self._container_client.get_blob_client(
        f"{self._kb_name}/.openkb/{resource}.lock"
    )
    lease_client = BlobLeaseClient(blob_client)
    deadline = time.monotonic() + timeout
    while True:
        try:
            await lease_client.acquire(lease_duration=60)
            break
        except ResourceExistsError:
            if time.monotonic() >= deadline:
                raise LockTimeoutError(resource)
            await asyncio.sleep(1.0)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await lease_client.release()
```

**Lock blob creation**: The lock blob must exist before a lease can be
acquired. `service_init_kb` writes an empty lock blob as part of KB
initialisation. All subsequent service functions check for KB existence before
attempting to lock.

**Alternatives considered**: Redis distributed lock (`redlock`) — adds a Redis
dependency for projects already committed to Azure Blob; Azure Storage Queue
message leases — more complex protocol, not idiomatic for mutex semantics.

---

## R-005 — Backend selection at startup

**Decision**: Read `OPENKB_STORAGE_BACKEND` (values: `local` | `azure`) at
API startup via a FastAPI lifespan function. Cache the factory as application
state. The `get_backend` dependency resolves a per-request `StorageBackend`
instance (local: one per `kb_name` path; Azure: one per `kb_name` prefix).

**Environment variables**:
```
OPENKB_STORAGE_BACKEND=local   # or azure
OPENKB_BASE_DIR=/data/kbs      # root dir for LocalStorageBackend (local only)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=...
AZURE_KB_CONTAINER=openkb
```

**Rationale**: Environment-variable selection satisfies FR-015 without any code
changes. `python-dotenv` (already a dependency) loads these from `.env` at
startup. The `get_backend` dependency factory pattern keeps the route handlers
backend-agnostic.

**`get_backend` dependency**:
```python
async def get_backend(
    kb_name: str = Query(..., description="KB slug"),
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

**Alternatives considered**: Config-file backend selection (rejected — env vars
are simpler, 12-factor compliant, and require no file changes to switch).

---

## R-006 — `openkb serve` CLI command

**Decision**: Add a `serve` command to the existing Click group in `cli.py`.
It calls `uvicorn.run(create_app(), host=host, port=port, reload=reload)`.
Options: `--host` (default `0.0.0.0`), `--port` (default `8000`),
`--reload` (dev mode flag).

**Rationale**: FR-011 requires the server to be startable via CLI. Wrapping
uvicorn in a Click command keeps the UX consistent with the existing CLI.
`create_app()` is the FastAPI app factory from `openkb/api/app.py`.

**Import guard**: The `serve` command import of `uvicorn` and `openkb.api`
is deferred to the command body so that `fastapi` and `uvicorn` are not
imported at CLI startup when the `[api]` extra is not installed.

```python
@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True)
@click.option("--reload", is_flag=True, default=False)
def serve(host, port, reload):
    """Start the OpenKB HTTP API server."""
    try:
        import uvicorn
        from openkb.api.app import create_app
    except ImportError:
        click.echo(
            "The [api] extra is required. Install with:\n"
            "  uv sync --extra api"
        )
        raise SystemExit(1)
    uvicorn.run(create_app(), host=host, port=port, reload=reload)
```

**Alternatives considered**: Separate `openkb-serve` entry point (rejected —
fragmentation; the Click group is the established pattern).

---

## R-007 — Service function refactoring strategy for `cli.py`

**Decision**: Extract five service functions into `openkb/services/`. Each
returns a plain dataclass result (not a Click-formatted string). The CLI
wrappers call the service functions and `click.echo` the results. This is the
minimum-invasive refactoring that achieves FR-008 and SC-004.

**Mapping**:

| CLI function / command | Extracted service | Return type |
|---|---|---|
| `init` command body | `service_init_kb` | `KBInitResult` |
| `add_single_file` / `_add_single_file_locked` | `service_add_document` | `KBAddResult` |
| `query` command body | `service_query_kb` | `KBQueryResult` |
| `print_list` | `service_list_kb` | `KBListResult` |
| `print_status` | `service_status_kb` | `KBStatusResult` |

**`print_list` / `print_status` refactor**: These are currently module-level
functions called by both the CLI commands and the chat REPL. The plan replaces
them with service functions that return structured data; the CLI wrappers then
format and print. The chat REPL is updated to call the service functions
directly (it currently calls `print_list(kb_dir)` and `print_status(kb_dir)`).

**`add_single_file` refactor**: The existing synchronous
`add_single_file(file_path, kb_dir)` is retained as a thin wrapper for the
CLI's hot path (it calls `asyncio.run(service_add_document(...))`). This
preserves any callers in tests or the watcher module without changes.

**Alternatives considered**: Leaving `cli.py` unchanged and duplicating logic
in service functions (rejected — violates FR-008 and Constitution §I).

---

## R-008 — Error shape and HTTP status mapping

**Decision**: A single `ErrorResponse(detail: str)` Pydantic model is used for
all error responses. FastAPI exception handlers in `app.py` catch custom
exceptions from the service layer and map them to HTTP status codes:

| Exception class | HTTP status | Scenario |
|---|---|---|
| `KBNotFoundError` | 404 | KB not initialised |
| `KBAlreadyExistsError` | 409 | `init` on existing KB |
| `DocumentSkippedError` | 200 (not error) | Already in registry |
| `LockTimeoutError` | 503 | Azure lease not acquired |
| `LLMError` | 502 | LLM API failure |
| `pydantic.ValidationError` | 422 | FastAPI handles automatically |

**Rationale**: Custom exception hierarchy in `openkb/services/__init__.py`
decouples the service layer from HTTP semantics. Route handlers and the CLI
both catch these exceptions and handle them appropriately for their surface.
Satisfies FR-010.

**Alternatives considered**: Raising `fastapi.HTTPException` directly from
service functions (rejected — couples service layer to HTTP; breaks CLI usage).

---

## R-009 — Test strategy for async FastAPI endpoints

**Decision**: Use `httpx.AsyncClient` with `ASGITransport(app=create_app())`
in `pytest-asyncio` async test functions. `LocalStorageBackend` is initialised
against a `tmp_path` pytest fixture. Azure backend tests mock
`BlobServiceClient` with `unittest.mock.AsyncMock`.

**Rationale**: `httpx.AsyncClient` + `ASGITransport` is the official FastAPI
testing pattern for async code. It avoids starting a real server while still
exercising the full ASGI stack. `pytest-asyncio` with `asyncio_mode = "auto"`
(in `pyproject.toml`) keeps test boilerplate minimal.

**Pattern**:
```python
@pytest.mark.asyncio
async def test_init_creates_kb(tmp_path):
    app = create_app(base_dir=tmp_path)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/kb/init", json={"kb_name": "my-kb"})
    assert resp.status_code == 200
    assert (tmp_path / "my-kb" / ".openkb" / "config.yaml").exists()
```

**Alternatives considered**: `TestClient` (sync) — works but hides async
issues; running a real uvicorn server in tests — slower, harder to isolate.

---

## Summary of Resolved Unknowns

| Unknown | Resolution |
|---|---|
| FastAPI version + Pydantic v2 requirement | `fastapi==0.137.2` requires Pydantic v2 (`>=2.9.0`); litellm already pulls it in transitively — no conflict |
| Azure Blob Lease locking pattern | R-004: `BlobLeaseClient.acquire` on a dedicated lock blob; 1 s polling; configurable timeout; auto-expire after 60 s |
| StorageBackend bridge to path-based compiler | R-003: `LocalStorageBackend.kb_dir` property; `AzureBlobStorageBackend.local_working_dir()` context manager for materialise-process-sync pattern |
| Backend selection without code changes | R-005: `OPENKB_STORAGE_BACKEND` env var; resolved in FastAPI lifespan |
| CLI serve command + import guard | R-006: deferred import of `uvicorn` / `openkb.api` inside command body |
| `print_list` / `print_status` refactor impact | R-007: chat REPL updated; `add_single_file` wrapper preserved; zero regressions |
| Async test client | R-009: `httpx.AsyncClient` + `ASGITransport`; `pytest-asyncio` auto mode |

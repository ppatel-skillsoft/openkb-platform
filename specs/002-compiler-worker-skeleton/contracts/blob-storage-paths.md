# Contract: Blob Storage Paths

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Storage backend**: Azure Blob Storage (production) / Azurite (local dev)  
**Client**: `azure-storage-blob` SDK v12 (`BlobServiceClient`)

---

## Overview

All blob access for a knowledge base is scoped to a single Azure Blob Storage
**container** named `kb-{kb_id}`. Within that container, source documents and
compiled wiki pages are stored under distinct prefixes.

---

## Container Naming

```
Container name:  kb-{kb_id}
Example:         kb-a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

The container name is derived from the `knowledge_bases.storage_container_path`
column (stored without trailing slash). The worker creates the container if it
does not exist (`create_container(exist_ok=True)`) before its first upload.

---

## Blob Paths

### Source Document (input)

```
{container}/raw/{filename}

Examples:
  kb-<uuid>/raw/report.md
  kb-<uuid>/raw/architecture-overview.pdf
  kb-<uuid>/raw/meeting-notes-2026-06-21.txt
```

The `blob_path` field in the job queue message carries the full
`{container}/raw/{filename}` path. The worker downloads this blob to
`{scratch_dir}/raw/{filename}` before spawning the sidecar.

### Compiled Wiki Page (output)

```
{container}/wiki/{slug}.md

Examples:
  kb-<uuid>/wiki/summaries/report.md
  kb-<uuid>/wiki/concepts/attention.md
  kb-<uuid>/wiki/entities/alan-turing.md
  kb-<uuid>/wiki/index.md
```

The `slug` value comes from the sidecar `GET /status` response. The worker
appends `.md` and prefixes `wiki/` to form the blob name. This blob path is
also stored in `wiki_pages.blob_path`.

---

## Path Construction Rules

| Variable | Source |
|---|---|
| `kb_id` | `CompilationJob.kb_id` (from queue message) |
| `container` | `knowledge_bases.storage_container_path` (queried from Postgres) |
| `filename` | `CompilationJob.filename` (from queue message) |
| `slug` | `SidecarPage.slug` (from sidecar `/status` response) |

```python
# Input download
input_blob_name = f"raw/{job.filename}"
blob_client = container_client.get_blob_client(input_blob_name)
data = blob_client.download_blob().readall()

# Output upload (per wiki page)
output_blob_name = f"wiki/{page.slug}.md"
output_blob_path = f"{container}/{output_blob_name}"  # stored in wiki_pages.blob_path
page_content = Path(scratch_dir / page.file_path).read_bytes()
container_client.get_blob_client(output_blob_name).upload_blob(
    page_content, overwrite=True
)
```

---

## Local Development (Azurite)

```
Connection string (default Azurite):
  DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;
  AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFor392Sdeds...;
  BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;

Environment variable:
  AZURE_STORAGE_CONNECTION_STRING=<above>
```

The Azurite default connection string is safe to commit to
`docker-compose.yml` as a non-secret development default.

---

## Production (Azure Blob Storage)

Set `AZURE_STORAGE_CONNECTION_STRING` to the real Azure connection string,
or use `DefaultAzureCredential` (managed identity). No code changes are
required — only the env var value changes.

---

## Constraints

- Blob names are case-sensitive.
- The `wiki/` prefix is reserved for compiled output; source documents MUST
  use the `raw/` prefix.
- Wiki page blobs are always overwritten on recompilation (`overwrite=True`);
  this is intentional and idempotent.
- Blob paths do NOT include a leading `/`.
- The `slug` value must not contain `.md` — the worker always appends `.md`
  when constructing the blob name.

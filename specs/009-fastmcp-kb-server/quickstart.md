# Quickstart: OpenKB MCP Server (feature/009)

**Audience**: Developer setting up the local stack and testing MCP tools end-to-end.
**Time**: ~20 minutes (excluding document compilation time).

---

## Prerequisites

- Docker and Docker Compose installed and running.
- `uv` installed (`brew install uv` or `curl -Ls https://astral.sh/uv/install.sh | sh`).
- `LLM_API_KEY` (OpenAI) available.
- Documents placed in `marketing_kb/` at the project root (not committed to git).

---

## Step 1: Configure environment

```bash
cp .env.docker .env
# Edit .env and set:
#   LLM_API_KEY=sk-...
```

---

## Step 2: Start the full stack

```bash
docker compose up --wait
```

All services — `postgres`, `migrate`, `azurite`, `api`, `compiler-worker`, `generator-api`, and the new `mcp-server` — start and report healthy.

Verify:

```bash
curl http://localhost:8002/health
# {"status":"ok","generator_api":"ok","detail":null}
```

---

## Step 3: Create the marketing KB and ingest documents

The ingestion script creates a KB named `marketing` (if it does not exist), uploads all documents from `marketing_kb/`, and queues compilation jobs:

```bash
uv run python scripts/ingest_marketing_kb.py \
  --kb-dir marketing_kb/ \
  --kb-name marketing
```

The script will:
1. Discover all `.docx`, `.pptx`, `.pdf`, `.txt`, `.md` files recursively.
2. Submit each to the `api` service with exponential-backoff retry (up to 5 attempts per file).
3. Print per-file status: `submitted` or `failed(reason)`.
4. Exit with code 0 if all files submitted; non-zero if any permanent failure.

Watch compilation progress:

```bash
# In another terminal:
docker compose logs -f compiler-worker
```

Documents move from `queued` → `compiling` → `complete`. The marketing KB with many documents may take 10–30 minutes to fully compile depending on OpenAI throughput.

---

## Step 4: Verify the KB is ready

```bash
# List ready KBs via the MCP tool (using fastmcp CLI):
uvx fastmcp run http://localhost:8002/mcp -- list_kbs '{}'
```

You should see the `marketing` KB with `document_count > 0` and `ready: true`.

---

## Step 5: Ask a question

```bash
uvx fastmcp run http://localhost:8002/mcp -- ask_kb '{
  "kb_id": "<uuid-from-list_kbs>",
  "question": "What are our competitive differentiators against Cornerstone?"
}'
```

Expected: a grounded answer with `citations` from the compiled wiki.

---

## Step 6: Connect an MCP host

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openkb": {
      "url": "http://localhost:8002/mcp",
      "transport": "streamable-http"
    }
  }
}
```

Restart Claude Desktop. The tools `ask_kb` and `list_kbs` will appear in the tools panel.

### Cursor

Add to `.cursor/mcp.json` in the project root:

```json
{
  "mcpServers": {
    "openkb": {
      "url": "http://localhost:8002/mcp",
      "transport": "http"
    }
  }
}
```

### GitHub Copilot (VS Code)

Add to `.github/copilot-mcp.json`:

```json
{
  "servers": {
    "openkb": {
      "type": "http",
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `mcp-server` container unhealthy | `generator-api` not yet healthy | Wait; `docker compose ps` to check all services |
| `ask_kb` returns "no compiled documents" | Compilation not finished | Check `docker compose logs compiler-worker` |
| Ingestion script exits with 429 errors | OpenAI rate limit not recoverable within retries | Reduce `--concurrency` to 1; re-run script (already-submitted docs will be skipped) |
| `list_kbs` returns empty list | No documents compiled yet | Wait for compiler-worker to finish |
| Cannot connect from Claude Desktop | Firewall / VPN blocking localhost:8002 | Disable VPN; check `curl http://localhost:8002/health` from host |

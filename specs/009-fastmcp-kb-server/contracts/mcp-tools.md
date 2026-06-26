# MCP Tool Contracts: OpenKB MCP Server

**Feature**: `009-fastmcp-kb-server`
**Transport**: Streamable HTTP — `http://localhost:8002/mcp`
**Protocol**: Model Context Protocol (MCP) 2025-03-26
**Server name**: `"OpenKB"`
**Server instructions**: "Query compiled knowledge bases. Use list_kbs to discover available knowledge bases, then ask_kb to get grounded answers with citations."

---

## Tool: `ask_kb`

Ask a natural-language question against a compiled knowledge base. Returns a grounded answer with source citations.

### Annotations

```python
annotations=ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    openWorldHint=True,
)
```

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "kb_id": {
      "type": "string",
      "description": "UUID of the knowledge base to query. Obtain from list_kbs.",
      "format": "uuid"
    },
    "question": {
      "type": "string",
      "description": "Natural-language question to answer. Maximum 8000 characters.",
      "minLength": 1,
      "maxLength": 8000
    }
  },
  "required": ["kb_id", "question"]
}
```

### Output Schema

```json
{
  "type": "object",
  "properties": {
    "answer": {
      "type": "string",
      "description": "Grounded answer derived from the compiled knowledge base."
    },
    "citations": {
      "type": "array",
      "description": "Source references from the compiled wiki that back the answer.",
      "items": {}
    },
    "tokens_used": {
      "type": "integer",
      "description": "Total tokens consumed for this query.",
      "minimum": 0
    },
    "kb_id": {
      "type": "string",
      "description": "Echoed knowledge base identifier for correlation."
    }
  },
  "required": ["answer", "citations", "tokens_used", "kb_id"]
}
```

### Error Responses (MCP structured errors)

| Condition | MCP Error Code | Message |
|---|---|---|
| `kb_id` is not a valid UUID | `INVALID_PARAMS` | `"kb_id must be a valid UUID"` |
| `question` is blank or too long | `INVALID_PARAMS` | `"question must be 1–8000 characters"` |
| KB not found in database | `INVALID_PARAMS` | `"Knowledge base {kb_id} not found"` |
| KB has no compiled documents | `INVALID_PARAMS` | `"Knowledge base {kb_id} has no compiled documents yet"` |
| `generator-api` timeout | `INTERNAL_ERROR` | `"Query timed out — the knowledge base may be initialising"` |
| `generator-api` unreachable | `INTERNAL_ERROR` | `"Knowledge base service unavailable"` |

---

## Tool: `list_kbs`

List all knowledge bases that have at least one compiled document and are ready to query.

### Annotations

```python
annotations=ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
```

### Input Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

No arguments. Call with an empty object `{}`.

### Output Schema

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "description": "UUID of the knowledge base. Pass as kb_id to ask_kb.",
        "format": "uuid"
      },
      "name": {
        "type": "string",
        "description": "Human-readable slug / name of the knowledge base."
      },
      "document_count": {
        "type": "integer",
        "description": "Number of successfully compiled documents.",
        "minimum": 1
      },
      "ready": {
        "type": "boolean",
        "description": "Always true — only ready KBs are included in this list.",
        "const": true
      }
    },
    "required": ["id", "name", "document_count", "ready"]
  }
}
```

### Error Responses

| Condition | MCP Error Code | Message |
|---|---|---|
| DB unreachable | `INTERNAL_ERROR` | `"Unable to retrieve knowledge base list"` |

---

## Health Endpoint (non-MCP, for Docker Compose)

`GET /health`

This route bypasses MCP auth middleware by design (FastMCP `custom_route` convention).

### Response

```json
{
  "status": "ok" | "degraded",
  "generator_api": "ok" | "error",
  "detail": null | "<error message>"
}
```

HTTP 200 when `status == "ok"`, HTTP 503 when `status == "degraded"`.

---

## MCP Client Configuration Examples

### Claude Desktop (`claude_desktop_config.json`)

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

### Cursor (`.cursor/mcp.json`)

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

### GitHub Copilot (`.github/copilot-mcp.json`)

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

### STDIO bridge (for hosts that only support STDIO)

```json
{
  "mcpServers": {
    "openkb": {
      "command": "uvx",
      "args": ["fastmcp", "run", "http://localhost:8002/mcp"]
    }
  }
}
```

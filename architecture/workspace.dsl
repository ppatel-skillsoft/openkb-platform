workspace "OpenKB Platform" "Level 2 Container diagram for the OpenKB Platform" {

    !identifiers hierarchical

    model {

        consumer = person "KB Consumer" "Uses an AI agent or MCP host to query a knowledge base in natural language"
        developer = person "Developer / KB Admin" "Seeds knowledge bases and manages documents"

        openai = softwareSystem "OpenAI API" "LLM inference used during KB compilation (summarisation and embeddings)" {
            tags "ExternalSystem"
        }

        aiHost = softwareSystem "AI Agent Host" "Claude Desktop, Cursor, GitHub Copilot, or any MCP-compatible agent" {
            tags "ExternalSystem"
        }

        openkb = softwareSystem "OpenKB Platform" "Compiles domain documents into queryable knowledge bases and exposes them via MCP" {
            tags "PrimarySystem"

            mcpServer = container "MCP Server" "Routes /{kb_slug}/mcp to a lazily-created FastMCP instance per KB. Manages ASGI lifespan via _ManagedApp. Exposes a single ask(question) tool per KB. GET /health checks Postgres." "Python 3.12 / FastMCP 3.4 / Starlette — :8002" {
                tags "AppContainer"
            }

            generatorApi = container "Generator API" "Per-request RAG queries: syncs wiki blobs to scratch dir, spawns openkb serve sidecar, queries, tears down. Also handles document deletion: soft-delete row, delete summary blob, rebuild index.md." "Python 3.12 / FastAPI 0.137 — :8001" {
                tags "AppContainer"
            }

            serveSidecar = container "openkb Serve Sidecar" "Ephemeral openkb serve subprocess spawned per query request. Loads wiki from scratch dir, answers the question, then exits. Managed entirely within a single request lifecycle." "openkb-core CLI (ephemeral, per-request)" {
                tags "SidecarContainer"
            }

            compilerWorker = container "Compiler Worker" "Polls Postgres job queue (SKIP LOCKED). Spawns an ephemeral openkb compile sidecar per document. Recovers stale jobs on startup." "Python 3.12 asyncio" {
                tags "AppContainer"
            }

            compileSidecar = container "openkb Compile Sidecar" "Ephemeral openkb compile subprocess spawned per document. Downloads source blob, calls OpenAI, uploads compiled wiki blobs (summaries/, concepts/, entities/, index.md), then exits." "openkb-core CLI (ephemeral, per-job)" {
                tags "SidecarContainer"
            }

            ingestScript = container "Ingest Script" "One-shot script (ingest_marketing_kb.py). Uploads source files to Blob Storage, writes KB and document rows directly to Postgres, enqueues compiler jobs. Semaphore(3) + tenacity retries for resilience." "Python 3.12 / SQLAlchemy asyncpg / Azure Blob SDK" {
                tags "ScriptContainer"
            }

            postgres = container "PostgreSQL" "Stores knowledge_bases, documents (with soft-delete), compiler_jobs queue, and wiki_pages metadata." "PostgreSQL 16" {
                tags "StorageContainer"
            }

            blobStorage = container "Blob Storage" "Two roles: (1) source documents uploaded by ingest script; (2) compiled wiki artefacts (wiki/summaries/, wiki/concepts/, wiki/entities/, wiki/index.md) per KB container." "Azure Blob Storage (Azurite locally)" {
                tags "StorageContainer"
            }
        }

        # ── External actor flows ──────────────────────────────────────────────
        consumer -> aiHost "Queries a knowledge base in natural language"
        developer -> openkb.ingestScript "Runs to seed a knowledge base with source documents"
        developer -> openkb.generatorApi "Deletes documents via REST API" "HTTP DELETE /kbs/{id}/documents/{doc_id}"

        # ── AI host → MCP Server ──────────────────────────────────────────────
        aiHost -> openkb.mcpServer "MCP Streamable HTTP /{kb_slug}/mcp" "HTTP"

        # ── MCP Server → Generator API ────────────────────────────────────────
        openkb.mcpServer -> openkb.generatorApi "Forwards ask tool call" "HTTP POST /kbs/{id}/query"
        openkb.mcpServer -> openkb.postgres "Resolves KB slug to UUID; checks compiled docs exist" "SQLAlchemy asyncpg"

        # ── Generator API ─────────────────────────────────────────────────────
        openkb.generatorApi -> openkb.postgres "Validates KB and document records; soft-deletes document on removal" "SQLAlchemy asyncpg"
        openkb.generatorApi -> openkb.blobStorage "Syncs wiki blobs to scratch dir (query); deletes summary blob and rebuilds index.md (delete)" "Azure Blob SDK"
        openkb.generatorApi -> openkb.serveSidecar "Spawns per-request subprocess; sends query; tears down" "subprocess stdio"

        # ── Ingest Script ─────────────────────────────────────────────────────
        openkb.ingestScript -> openkb.blobStorage "Uploads source document files" "Azure Blob SDK"
        openkb.ingestScript -> openkb.postgres "Writes KB row, document rows, enqueues compiler_jobs" "SQLAlchemy asyncpg"

        # ── Compiler Worker ───────────────────────────────────────────────────
        openkb.compilerWorker -> openkb.postgres "Claims jobs atomically (DELETE … RETURNING, SKIP LOCKED); updates document status" "SQLAlchemy asyncpg"
        openkb.compilerWorker -> openkb.compileSidecar "Spawns per-document compilation subprocess" "subprocess stdio"

        # ── Compile Sidecar ───────────────────────────────────────────────────
        openkb.compileSidecar -> openkb.blobStorage "Downloads source doc; uploads compiled wiki blobs" "Azure Blob SDK"
        openkb.compileSidecar -> openai "LLM calls for summarisation and embedding" "HTTPS"
    }

    views {
        container openkb "Level2Containers" "Level 2 Container diagram — OpenKB Platform" {
            include consumer
            include developer
            include aiHost
            include openai
            include *
            autoLayout lr 150 120
        }

        styles {
            element "Person" {
                shape Person
                background #f4f4f4
                stroke #1f2937
                color #1f2937
            }

            element "Software System" {
                shape roundedBox
                background #dae8fc
                stroke #6c8ebf
                color #1f2937
            }

            element "PrimarySystem" {
                shape roundedBox
                background #e8f4e8
                stroke #4b5563
                color #1f2937
            }

            element "ExternalSystem" {
                shape roundedBox
                background #dae8fc
                stroke #6c8ebf
                color #1f2937
            }

            element "Container" {
                shape roundedBox
                background #d5e8d4
                stroke #82b366
                color #1f2937
            }

            element "AppContainer" {
                shape roundedBox
                background #ffe6cc
                stroke #d79b00
                color #1f2937
            }

            element "ScriptContainer" {
                shape roundedBox
                background #e8d5f5
                stroke #9c27b0
                color #1f2937
            }

            element "SidecarContainer" {
                shape roundedBox
                background #fff2cc
                stroke #d6b656
                color #1f2937
            }

            element "StorageContainer" {
                shape Cylinder
                background #d5e8d4
                stroke #82b366
                color #1f2937
            }
        }
    }
}

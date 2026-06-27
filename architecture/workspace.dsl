workspace "OpenKB Platform" "Level 2 Container diagram for the OpenKB Platform" {

    !identifiers hierarchical

    model {

        consumer = person "KB Consumer" "Uses an AI agent or MCP host to query a knowledge base in natural language"
        developer = person "Developer / KB Admin" "Ingests source documents and manages knowledge bases via scripts and API"

        openai = softwareSystem "OpenAI API" "LLM inference used during KB compilation (embeddings and summarisation)" {
            tags "ExternalSystem"
        }

        aiHost = softwareSystem "AI Agent Host" "Claude Desktop, Cursor, GitHub Copilot, or any MCP-compatible agent" {
            tags "ExternalSystem"
        }

        openkb = softwareSystem "OpenKB Platform" "Compiles domain documents into queryable knowledge bases and exposes them via MCP" {
            tags "PrimarySystem"

            mcpServer = container "MCP Server" "Provides a per-KB MCP endpoint. Lazily creates one FastMCP app per KB slug and manages its ASGI lifespan. Exposes a single ask tool." "Python 3.12 / FastMCP 3.4 — :8002" {
                tags "AppContainer"
            }

            generatorApi = container "Generator API" "Handles RAG queries via openkb serve sidecars. Handles document deletion: soft-delete DB row, remove summary blob, rebuild index." "Python 3.12 / FastAPI 0.137 — :8001" {
                tags "AppContainer"
            }

            ingestScript = container "Ingest Script" "One-shot script that registers KBs and documents directly in Postgres and enqueues compiler jobs. Uses tenacity + Semaphore(3) to avoid OpenAI 429 errors." "Python 3.12 / SQLAlchemy asyncpg" {
                tags "ScriptContainer"
            }

            compilerWorker = container "Compiler Worker" "Polls the Postgres job queue with SKIP LOCKED and spawns an ephemeral openkb compile sidecar per document." "Python 3.12 asyncio" {
                tags "AppContainer"
            }

            sidecarPool = container "Sidecar Pool" "Maintains one persistent openkb serve process per active KB (lazy start, reused across requests). Lives inside the Generator API process." "Python 3.12 / openkb-core (SidecarPool)" {
                tags "SidecarContainer"
            }

            compileSidecar = container "Compile Sidecar" "Short-lived openkb compile subprocess spawned per document. Calls OpenAI, writes wiki blobs, then exits." "openkb-core CLI (ephemeral)" {
                tags "SidecarContainer"
            }

            postgres = container "PostgreSQL" "Stores knowledge base metadata, document records with soft-delete, and the compiler job queue." "PostgreSQL 16" {
                tags "StorageContainer"
            }

            blobStorage = container "Blob Storage" "Stores compiled wiki artefacts per KB: summaries/, concepts/, entities/, index.md." "Azure Blob Storage (Azurite locally)" {
                tags "StorageContainer"
            }
        }

        # ── External actor flows ──────────────────────────────────────────────
        consumer -> aiHost "Queries a knowledge base in natural language"
        developer -> openkb.ingestScript "Runs to seed a knowledge base with source documents"
        developer -> openkb.generatorApi "Deletes documents via REST API" "HTTP DELETE"

        # ── AI host → MCP Server ──────────────────────────────────────────────
        aiHost -> openkb.mcpServer "MCP Streamable HTTP  /{kb_slug}/mcp" "HTTP"

        # ── MCP Server → Generator API ────────────────────────────────────────
        openkb.mcpServer -> openkb.generatorApi "Forwards ask tool call" "HTTP  POST /kbs/{id}/query"

        # ── Generator API internals ───────────────────────────────────────────
        openkb.generatorApi -> openkb.sidecarPool "Routes query to active sidecar" "in-process"
        openkb.generatorApi -> openkb.postgres "Resolves KB and document records; soft-deletes on removal" "SQLAlchemy asyncpg"
        openkb.generatorApi -> openkb.blobStorage "Deletes summary blob and rebuilds index on document removal" "Azure Blob SDK"

        # ── Sidecar Pool ──────────────────────────────────────────────────────
        openkb.sidecarPool -> openkb.blobStorage "Reads wiki index and summaries for RAG" "Azure Blob SDK"

        # ── Ingest Script ─────────────────────────────────────────────────────
        openkb.ingestScript -> openkb.postgres "Writes KB and document records; enqueues compiler jobs" "SQLAlchemy asyncpg"

        # ── Compiler Worker ───────────────────────────────────────────────────
        openkb.compilerWorker -> openkb.postgres "Claims compiler jobs (DELETE … RETURNING, SKIP LOCKED)" "SQLAlchemy asyncpg"
        openkb.compilerWorker -> openkb.compileSidecar "Spawns per-document compilation subprocess" "subprocess stdio"

        # ── Compile Sidecar ───────────────────────────────────────────────────
        openkb.compileSidecar -> openkb.blobStorage "Uploads compiled summaries, concepts, entities, index" "Azure Blob SDK"
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

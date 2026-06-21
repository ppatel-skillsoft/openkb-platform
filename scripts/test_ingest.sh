#!/usr/bin/env bash
# test_ingest.sh — End-to-end smoke test for the compiler-worker pipeline.
#
# Usage:
#   ./scripts/test_ingest.sh [path/to/document.md]
#
# Defaults to a small inline Markdown file if no argument is given.
# Requires: docker compose stack running, az CLI installed.

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${YELLOW}══ $* ══${NC}"; }

# ── Config ────────────────────────────────────────────────────────────────────
KB_ID="00000000-0000-0000-0000-000000000001"
KB_SLUG="test-kb"
CONTAINER_NAME="kb-${KB_ID}"
BLOB_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;"
WAIT_SECONDS=30   # max seconds to wait for worker to process the job

# ── Input file ────────────────────────────────────────────────────────────────
if [[ $# -ge 1 ]]; then
  INPUT_FILE="$1"
  if [[ ! -f "$INPUT_FILE" ]]; then
    error "File not found: $INPUT_FILE"
    exit 1
  fi
  FILENAME=$(basename "$INPUT_FILE")
else
  # Default: write a temp Markdown file
  INPUT_FILE=$(mktemp /tmp/openkb-test-XXXX.md)
  FILENAME="hello.md"
  cat > "$INPUT_FILE" <<'EOF'
# Hello OpenKB

This is an end-to-end smoke test document.

## Section 1

Some content to compile into a wiki page.

## Section 2

More content here.
EOF
  info "No file supplied — using temporary file: $INPUT_FILE"
fi

BLOB_PATH="${CONTAINER_NAME}/raw/${FILENAME}"

# ── Prerequisites ─────────────────────────────────────────────────────────────
section "Checking prerequisites"

if ! docker compose ps --quiet 2>/dev/null | grep -q .; then
  error "Docker Compose stack is not running. Start it with: docker compose up -d"
  exit 1
fi

for svc in postgres redis azurite compiler-worker; do
  state=$(docker compose ps --format json "$svc" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('State','unknown'))" 2>/dev/null || echo "unknown")
  if [[ "$state" != "running" ]]; then
    error "Service '$svc' is not running (state: $state). Run: docker compose up -d"
    exit 1
  fi
done
info "All required services are running"

if ! command -v az &>/dev/null; then
  error "Azure CLI (az) not found. Install it to upload blobs to Azurite."
  exit 1
fi

# ── Step 1: Blob container ────────────────────────────────────────────────────
section "Step 1 — Ensure blob container exists"

az storage container create \
  --name "$CONTAINER_NAME" \
  --connection-string "$BLOB_CONNECTION_STRING" \
  --output none 2>/dev/null && info "Container '$CONTAINER_NAME' ready" \
  || warn "Container create returned non-zero (may already exist — continuing)"

# ── Step 2: Seed Postgres ─────────────────────────────────────────────────────
section "Step 2 — Seed Postgres (KB + document rows)"

psql() {
  docker compose exec -T postgres psql -U openkb -d openkb "$@"
}

psql -c "
  INSERT INTO knowledge_bases (id, name, slug, status)
  VALUES ('${KB_ID}', '${KB_SLUG}', '${KB_SLUG}', 'active')
  ON CONFLICT (id) DO NOTHING;
" > /dev/null
info "KB row ensured (id=${KB_ID})"

DOC_ID=$(psql -t -c "
  INSERT INTO documents (kb_id, source_type, original_filename, status)
  VALUES ('${KB_ID}', 'upload', '${FILENAME}', 'pending')
  RETURNING id;
" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)

if [[ -z "$DOC_ID" ]]; then
  error "Failed to insert document row"
  exit 1
fi
info "Document row created (id=${DOC_ID})"

# ── Step 3: Upload blob ───────────────────────────────────────────────────────
section "Step 3 — Upload blob to Azurite"

az storage blob upload \
  --container-name "$CONTAINER_NAME" \
  --name "raw/${FILENAME}" \
  --file "$INPUT_FILE" \
  --overwrite \
  --connection-string "$BLOB_CONNECTION_STRING" \
  --output none
info "Blob uploaded: ${BLOB_PATH}"

# ── Step 4: Enqueue job ───────────────────────────────────────────────────────
section "Step 4 — Enqueue compilation job"

JOB_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
ENQUEUED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
JOB_JSON=$(printf '{"job_id":"%s","kb_id":"%s","document_id":"%s","blob_path":"%s","filename":"%s","enqueued_at":"%s"}' \
  "$JOB_ID" "$KB_ID" "$DOC_ID" "$BLOB_PATH" "$FILENAME" "$ENQUEUED_AT")

docker compose exec -T redis redis-cli LPUSH compiler:jobs "$JOB_JSON" > /dev/null
info "Job enqueued (job_id=${JOB_ID})"

# ── Step 5: Wait for result ───────────────────────────────────────────────────
section "Step 5 — Waiting up to ${WAIT_SECONDS}s for worker to process job"

ELAPSED=0
STATUS=""
while [[ $ELAPSED -lt $WAIT_SECONDS ]]; do
  STATUS=$(psql -t -c "SELECT status FROM documents WHERE id='${DOC_ID}';" | tr -d ' \n\r')
  if [[ "$STATUS" == "complete" || "$STATUS" == "compiled" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  echo -n "."
done
echo ""

# ── Step 6: Results ───────────────────────────────────────────────────────────
section "Step 6 — Results"

info "Document status: ${STATUS}"

if [[ "$STATUS" == "complete" || "$STATUS" == "compiled" ]]; then
  echo -e "${GREEN}✓ SUCCESS${NC} — document compiled"
  echo ""
  echo "Wiki pages written:"
  psql -c "SELECT slug, page_type, blob_path FROM wiki_pages WHERE kb_id='${KB_ID}' ORDER BY created_at DESC LIMIT 10;"
elif [[ "$STATUS" == "failed" ]]; then
  REASON=$(psql -t -c "SELECT failure_reason FROM documents WHERE id='${DOC_ID}';" | tr -d '[:space:]' | head -1)
  echo -e "${RED}✗ FAILED${NC} — failure_reason: ${REASON}"
  echo ""
  warn "Showing last 30 lines of compiler-worker logs:"
  docker compose logs --tail 30 compiler-worker
  exit 1
else
  warn "Job did not complete within ${WAIT_SECONDS}s (current status: ${STATUS})"
  warn "Check logs: docker compose logs -f compiler-worker"
  exit 1
fi

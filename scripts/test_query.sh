#!/usr/bin/env bash
# test_query.sh — End-to-end smoke test for the generator-api service.
#
# Usage:
#   ./scripts/test_query.sh                      # uses default test KB
#   ./scripts/test_query.sh "What is OpenKB?"    # custom question
#
# Prerequisites: Docker Compose stack running (postgres, azurite, generator-api)
# If no compiled documents exist, runs test_ingest.sh first to seed the KB.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[1;34m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
section() { echo -e "\n${BLUE}══ $* ══${NC}"; }

KB_ID="00000000-0000-0000-0000-000000000001"
QUESTION="${1:-What is this document about?}"
GENERATOR_URL="http://localhost:8001"

# ── DB helper ─────────────────────────────────────────────────────────────────
psql() {
  PGPASSWORD=openkb docker compose exec -T postgres \
    psql -U openkb -d openkb "$@"
}

# ── Step 0: Prerequisites ─────────────────────────────────────────────────────
section "Checking prerequisites"

for svc in postgres azurite generator-api; do
  if ! docker compose ps "$svc" 2>/dev/null | grep -q "healthy\|running"; then
    warn "$svc is not running — starting stack..."
    docker compose up -d postgres azurite generator-api
    sleep 5
    break
  fi
done

# Wait for generator-api health
MAX_WAIT=30
ELAPSED=0
until curl -sf "${GENERATOR_URL}/health" > /dev/null 2>&1; do
  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    echo -e "${RED}[ERROR]${NC} generator-api not healthy after ${MAX_WAIT}s"
    docker compose logs --tail 20 generator-api
    exit 1
  fi
  sleep 2; ELAPSED=$((ELAPSED + 2)); echo -n "."
done
echo ""
info "generator-api is healthy"

# ── Step 1: Ensure KB has a compiled document ─────────────────────────────────
section "Step 1 — Checking for compiled documents"

COMPILED_COUNT=$(psql -t -c "SELECT COUNT(*) FROM documents WHERE kb_id='${KB_ID}' AND status='complete';" | tr -d ' \n\r')

if [[ "$COMPILED_COUNT" == "0" || -z "$COMPILED_COUNT" ]]; then
  warn "No compiled documents found for KB ${KB_ID} — running test_ingest.sh first"
  "${SCRIPT_DIR}/test_ingest.sh"
else
  info "${COMPILED_COUNT} compiled document(s) found — proceeding with query"
fi

# ── Step 2: Send query ────────────────────────────────────────────────────────
section "Step 2 — Sending query"
info "Question: ${QUESTION}"

RESPONSE=$(curl -sf -X POST \
  "${GENERATOR_URL}/kbs/${KB_ID}/query" \
  -H "Content-Type: application/json" \
  -d "{\"question\": $(echo "${QUESTION}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')}" \
  2>&1) || {
  echo -e "${RED}[ERROR]${NC} Request failed"
  echo "$RESPONSE"
  docker compose logs --tail 30 generator-api
  exit 1
}

# ── Step 3: Validate response ─────────────────────────────────────────────────
section "Step 3 — Results"

ANSWER=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('answer',''))" 2>/dev/null || echo "")
TOKENS=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tokens_used',0))" 2>/dev/null || echo "0")
CITATIONS=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('citations',[])))" 2>/dev/null || echo "0")

if [[ -z "$ANSWER" ]]; then
  echo -e "${RED}✗ FAILED${NC} — empty answer received"
  echo "Raw response: ${RESPONSE}"
  exit 1
fi

echo -e "${GREEN}✓ SUCCESS${NC}"
echo ""
echo "Answer:"
echo "$ANSWER"
echo ""
info "Citations: ${CITATIONS} | Tokens used: ${TOKENS}"

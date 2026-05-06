#!/bin/bash
# Health check for n8n competitor intelligence pipeline
# Cron: */5 * * * * /opt/juststatistics_competitor_analysis/scripts/health_check.sh
#
# Checks: Docker containers running, PostgreSQL accepting connections, n8n HTTP 200
# On success: pings $HEARTBEAT_URL (BetterUptime / UptimeRobot)
# On failure: writes to LOG_FILE and exits 1

set -euo pipefail

LOG_FILE="/var/log/n8n-health.log"
COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1" | tee -a "$LOG_FILE"
}

fail() {
    log "FAIL: $1"
    exit 1
}

# Check 1: Docker containers running
cd "$COMPOSE_DIR"

N8N_STATUS=$(docker compose ps --format json n8n 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('State','unknown'))" 2>/dev/null \
    || echo "unknown")

PG_STATUS=$(docker compose ps --format json postgres 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('State','unknown'))" 2>/dev/null \
    || echo "unknown")

[ "$N8N_STATUS" = "running" ] || fail "n8n container not running (state: $N8N_STATUS)"
[ "$PG_STATUS" = "running" ] || fail "postgres container not running (state: $PG_STATUS)"

# Check 2: PostgreSQL accepts connections
docker compose exec -T postgres pg_isready \
    -U "${POSTGRES_USER:-n8n_admin}" \
    -d "${POSTGRES_DB:-n8n}" \
    > /dev/null 2>&1 || fail "PostgreSQL not accepting connections"

# Check 3: n8n HTTP healthz responds
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    -u "${N8N_BASIC_AUTH_USER}:${N8N_BASIC_AUTH_PASSWORD}" \
    "http://localhost:5678/healthz" 2>/dev/null || echo "000")

[ "$HTTP_STATUS" = "200" ] || fail "n8n healthz returned HTTP $HTTP_STATUS"

# All checks passed
log "OK: all checks passed"

if [ -n "${HEARTBEAT_URL:-}" ]; then
    curl -s --max-time 5 "$HEARTBEAT_URL" > /dev/null 2>&1 \
        || log "WARN: heartbeat ping failed (non-fatal)"
fi

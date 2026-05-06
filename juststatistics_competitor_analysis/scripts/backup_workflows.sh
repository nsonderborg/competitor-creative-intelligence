#!/bin/bash
# Exports all n8n workflows via API and saves timestamped JSON to n8n/backup/
# Cron: 0 2 * * * /opt/juststatistics_competitor_analysis/scripts/backup_workflows.sh
# Retains last 30 backups (auto-prunes older)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/../n8n/backup"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

HTTP_STATUS=$(curl -s -o "${BACKUP_DIR}/workflows_${DATE}.json" \
    -w "%{http_code}" \
    -u "${N8N_BASIC_AUTH_USER}:${N8N_BASIC_AUTH_PASSWORD}" \
    -H "Accept: application/json" \
    "http://localhost:5678/api/v1/workflows")

if [ "$HTTP_STATUS" != "200" ]; then
    rm -f "${BACKUP_DIR}/workflows_${DATE}.json"
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: n8n API returned HTTP $HTTP_STATUS" >&2
    exit 1
fi

# Keep last 30 backups
ls -t "${BACKUP_DIR}"/workflows_*.json 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Backup complete: workflows_${DATE}.json"

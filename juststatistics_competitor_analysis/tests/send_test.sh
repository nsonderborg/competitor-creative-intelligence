#!/bin/bash
# Sends mock_payload.json to your n8n webhook trigger
#
# Usage:
#   # Local Docker n8n (default):
#   ./tests/send_test.sh
#
#   # VPS n8n:
#   N8N_URL=https://your-domain.com ./tests/send_test.sh
#
# Prerequisite: set your webhook path in n8n and update WEBHOOK_PATH below

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD_FILE="${SCRIPT_DIR}/mock_payload.json"

N8N_URL="${N8N_URL:-http://localhost:5678}"
WEBHOOK_PATH="${WEBHOOK_PATH:-webhook/competitor-intelligence}"

FULL_URL="${N8N_URL}/${WEBHOOK_PATH}"

# Check payload has a real image (not the placeholder)
if grep -q "REPLACE_WITH_BASE64_STRING" "$PAYLOAD_FILE"; then
    echo "Warning: payload still has placeholder image."
    echo "Run: ./tests/inject_screenshot.sh /path/to/screenshot.png"
    echo ""
    echo "Continuing anyway (Vision Analyst node will fail but review nodes will work)..."
    echo ""
fi

echo "Sending test payload to: $FULL_URL"
echo "Brand: $(python3 -c "import json; d=json.load(open('${PAYLOAD_FILE}')); print(d['brand_name'])")"
echo "Reviews: $(python3 -c "import json; d=json.load(open('${PAYLOAD_FILE}')); print(len(d['review_texts']))")"
echo ""

HTTP_STATUS=$(curl -s -o /tmp/n8n_response.json -w "%{http_code}" \
    -X POST "$FULL_URL" \
    -H "Content-Type: application/json" \
    -d @"$PAYLOAD_FILE")

echo "HTTP status: $HTTP_STATUS"
echo ""

if [ "$HTTP_STATUS" = "200" ]; then
    echo "Response:"
    python3 -m json.tool /tmp/n8n_response.json 2>/dev/null || cat /tmp/n8n_response.json
else
    echo "Error response:"
    cat /tmp/n8n_response.json
    exit 1
fi

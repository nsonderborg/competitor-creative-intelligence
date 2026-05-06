#!/bin/bash
# Converts a local screenshot to base64 and injects it into mock_payload.json
#
# Usage:
#   ./tests/inject_screenshot.sh /path/to/screenshot.png
#   ./tests/inject_screenshot.sh ~/Desktop/competitor_ad.jpg
#
# Result: mock_payload.json updated with real base64 image, ready to send

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD_FILE="${SCRIPT_DIR}/mock_payload.json"

if [ -z "${1:-}" ]; then
    echo "Usage: $0 /path/to/screenshot.png"
    echo ""
    echo "Tip: take a screenshot of a Meta Ads Library ad, then run:"
    echo "  $0 ~/Desktop/ad_screenshot.png"
    exit 1
fi

IMAGE_PATH="$1"

if [ ! -f "$IMAGE_PATH" ]; then
    echo "Error: file not found: $IMAGE_PATH"
    exit 1
fi

# Detect media type from extension
case "${IMAGE_PATH##*.}" in
    jpg|jpeg) MEDIA_TYPE="image/jpeg" ;;
    png)      MEDIA_TYPE="image/png" ;;
    webp)     MEDIA_TYPE="image/webp" ;;
    *)        MEDIA_TYPE="image/jpeg" ;;
esac

# Encode to base64 (cross-platform: works on macOS and Linux)
if command -v base64 &>/dev/null; then
    B64=$(base64 -i "$IMAGE_PATH" | tr -d '\n')
else
    echo "Error: base64 command not found"
    exit 1
fi

# Inject into payload using Python (avoids sed issues with long base64 strings)
python3 -c "
import json, sys

with open('${PAYLOAD_FILE}', 'r') as f:
    payload = json.load(f)

payload['ad_screenshots'][0]['data'] = '${B64}'
payload['ad_screenshots'][0]['media_type'] = '${MEDIA_TYPE}'

with open('${PAYLOAD_FILE}', 'w') as f:
    json.dump(payload, f, indent=2)

print('Injected: ${IMAGE_PATH}')
print('Media type: ${MEDIA_TYPE}')
print('Base64 length: ' + str(len('${B64}')) + ' chars')
"

echo "Done. Run tests/send_test.sh to fire the payload at n8n."

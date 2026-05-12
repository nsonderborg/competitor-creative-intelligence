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

# Inject into payload using Python — reads image file directly to avoid arg length limits
python3 - <<PYEOF
import json, base64

image_path = '${IMAGE_PATH}'
media_type = '${MEDIA_TYPE}'
payload_file = '${PAYLOAD_FILE}'

with open(image_path, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()

with open(payload_file, 'r') as f:
    payload = json.load(f)

payload['ad_screenshots'][0]['data'] = b64
payload['ad_screenshots'][0]['media_type'] = media_type
payload['ad_screenshots'][0]['source_type'] = 'base64'

with open(payload_file, 'w') as f:
    json.dump(payload, f, indent=2)

print(f'Injected: {image_path}')
print(f'Media type: {media_type}')
print(f'Base64 length: {len(b64)} chars')
PYEOF

echo "Done. Run tests/send_test.sh to fire the payload at n8n."

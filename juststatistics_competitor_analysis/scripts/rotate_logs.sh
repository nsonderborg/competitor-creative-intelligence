#!/bin/bash
# Log rotation for n8n health and backup logs
# Cron: 0 3 * * 0 /opt/juststatistics_competitor_analysis/scripts/rotate_logs.sh

for LOG_FILE in /var/log/n8n-health.log /var/log/n8n-backup.log; do
    if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 5242880 ]; then
        mv "$LOG_FILE" "${LOG_FILE}.$(date +%Y%m%d)"
        gzip "${LOG_FILE}.$(date +%Y%m%d)" 2>/dev/null || true
        touch "$LOG_FILE"
    fi
done

# Remove rotated logs older than 30 days
find /var/log -name "n8n-*.log.*.gz" -mtime +30 -delete 2>/dev/null || true

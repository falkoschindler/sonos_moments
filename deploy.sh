#!/usr/bin/env bash
set -euo pipefail

# Deploy to a Raspberry Pi (or any Linux host) running Sonos Moments as a systemd service.
# Usage: ./deploy.sh [user@host]
#
# Without an argument the target comes from $SONOS_MOMENTS_HOST, so your own
# host name does not have to live in this repository.

TARGET="${1:-${SONOS_MOMENTS_HOST:-pi@raspberrypi.local}}"
REMOTE_DIR="sonos_moments"
SERVICE="sonos_moments"
HOST="${TARGET#*@}"

echo "==> Syncing to ${TARGET}:${REMOTE_DIR}"
livesync --no-watch . "${TARGET}:${REMOTE_DIR}"

echo "==> Installing dependencies and restarting ${SERVICE}"
# -4 because the .local name may also resolve to an unreachable IPv6 address.
ssh -4 "${TARGET}" "cd ${REMOTE_DIR} && ~/.local/bin/uv sync && sudo systemctl restart ${SERVICE}"

echo "==> Waiting for the service to come up"
for _ in $(seq 1 20); do
    if curl -sf -o /dev/null --max-time 5 "http://${HOST}:8081/"; then
        echo "==> Done: http://${HOST}:8081"
        exit 0
    fi
    sleep 3
done

echo "==> Service did not respond in time, check the logs:"
echo "    ssh -4 ${TARGET} 'journalctl -u ${SERVICE} -n 30 --no-pager'"
exit 1

#!/usr/bin/env bash
set -euo pipefail

# One-time setup of a freshly flashed Raspberry Pi to run Sonos Moments.
# Run this from your machine after the Pi is reachable over SSH:
#
#     ./setup.sh [user@host]
#
# Without an argument the target comes from $SONOS_MOMENTS_HOST, so your own
# host name does not have to live in this repository.
#
# Afterwards, ./deploy.sh ships the code. Enabling the read-only overlay is a
# separate, deliberate step - see the end of this script.

TARGET="${1:-${SONOS_MOMENTS_HOST:-pi@raspberrypi.local}}"
USER_NAME="${TARGET%@*}"
HOST="${TARGET#*@}"
REMOTE_DIR="sonos_moments"
SERVICE="sonos_moments"

# -4 because the .local name may also resolve to an unreachable IPv6 address.
# accept-new because we drop the host keys just below and would otherwise be
# asked to confirm the new one, which fails whenever this runs unattended.
SSH="ssh -4 -o StrictHostKeyChecking=accept-new"

echo "==> Dropping stale host keys"
# A freshly flashed card generates new host keys, so the remembered ones no
# longer match. Cover both the plain name and the .local form.
for name in "$HOST" "${HOST%.local}" "${HOST%.local}.local"; do
    ssh-keygen -R "$name" >/dev/null 2>&1 || true
done

echo "==> Installing uv"
$SSH "$TARGET" 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> Creating ${REMOTE_DIR} and moving NiceGUI storage to the boot partition"
# The boot partition is FAT32 and stays writable under the overlay, so the
# moments survive a reboot while the root filesystem never gets written to.
$SSH "$TARGET" "bash -s ${REMOTE_DIR}" <<'REMOTE'
set -e
REMOTE_DIR=$1
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot

# FAT32 carries no ownership of its own - the mount options decide who may
# write, and chown on it simply fails. Without this the service cannot save a
# moment. Only the options field of that one fstab line is touched.
if ! findmnt -n -o OPTIONS "$BOOT" | grep -q "uid=$(id -u)"; then
    echo "    handing $BOOT to $(id -un) in /etc/fstab"
    awk -v mnt="$BOOT" -v opts="uid=$(id -u),gid=$(id -g)" -v OFS='\t' \
        '$2 == mnt && $3 == "vfat" { $4 = $4 "," opts } { print }' \
        /etc/fstab > /tmp/fstab.new
    sudo cp /tmp/fstab.new /etc/fstab
    rm -f /tmp/fstab.new
    # vfat fixes uid and gid at mount time and ignores them on a remount, so
    # the partition has to go all the way down and up again.
    sudo umount "$BOOT" && sudo mount "$BOOT"
fi

mkdir -p ~/"$REMOTE_DIR"
mkdir -p "$BOOT/nicegui"
rm -rf ~/"$REMOTE_DIR"/.nicegui
ln -s "$BOOT/nicegui" ~/"$REMOTE_DIR"/.nicegui
echo "    .nicegui -> $BOOT/nicegui"
REMOTE

echo "==> Installing the systemd unit"
$SSH "$TARGET" "sudo tee /etc/systemd/system/${SERVICE}.service > /dev/null <<EOF
[Unit]
Description=Sonos Moments
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/${USER_NAME}/${REMOTE_DIR}
User=${USER_NAME}
Group=${USER_NAME}

ExecStart=/home/${USER_NAME}/${REMOTE_DIR}/.venv/bin/sonos-moments --port 8081

Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE} >/dev/null 2>&1"

echo "==> Reducing writes to the card"
$SSH "$TARGET" '
    sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
    sudo mkdir -p /etc/systemd/journald.conf.d
    echo -e "[Journal]\nStorage=volatile\nRuntimeMaxUse=16M" | sudo tee /etc/systemd/journald.conf.d/volatile.conf > /dev/null
'

echo
echo "==> Done. Next:"
echo "    ./deploy.sh ${TARGET}"
echo
echo "    Once that works, make the card read-only so pulling the plug is safe:"
echo "        ssh -4 ${TARGET} 'sudo raspi-config nonint enable_overlayfs && sudo reboot'"
echo "    To deploy again later, turn it off, deploy, turn it back on:"
echo "        ssh -4 ${TARGET} 'sudo raspi-config nonint disable_overlayfs && sudo reboot'"

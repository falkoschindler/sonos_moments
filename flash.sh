#!/usr/bin/env bash
set -euo pipefail

# Flash Raspberry Pi OS Lite onto an SD card and preconfigure the first boot,
# so that a headless board comes up on the network by itself.
# Usage: ./flash.sh [user@host]
#
# Without an argument the target comes from $SONOS_MOMENTS_HOST. The host part
# becomes the hostname, the user part the account. Wifi credentials are asked
# for interactively and never stored in plain text.
#
# Afterwards, ./setup.sh installs the service and ./deploy.sh ships the code.
#
# This talks to diskutil and therefore only runs on macOS. What it writes is
# the cloud-init form that Raspberry Pi OS Trixie expects ("cloudinit-rpi"),
# the same thing the Raspberry Pi Imager 2.x produces - see
# https://github.com/raspberrypi/rpi-imager/blob/HEAD/doc/os_customisation_formats.md

TARGET="${1:-${SONOS_MOMENTS_HOST:-pi@raspberrypi.local}}"
USER_NAME="${TARGET%@*}"
HOST_NAME="${TARGET#*@}"
HOST_NAME="${HOST_NAME%.local}"

COUNTRY="${WIFI_COUNTRY:-DE}"
TIMEZONE="${TIMEZONE:-Europe/Berlin}"
KEYMAP="${KEYMAP:-de}"
PUBKEY_FILE="${SSH_PUBKEY:-}"

INDEX=https://downloads.raspberrypi.com/raspios_lite_arm64/images
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/sonos-moments"
MAX_SIZE=137438953472   # refuse anything larger than 128 GB - not a card we expect

[ "$(uname)" = "Darwin" ] || { echo "ABORT: this script uses diskutil and only runs on macOS"; exit 1; }

if [ -z "$PUBKEY_FILE" ]; then
    for candidate in ~/.ssh/id_ed25519.pub ~/.ssh/id_rsa.pub; do
        [ -f "$candidate" ] && { PUBKEY_FILE="$candidate"; break; }
    done
fi
[ -n "$PUBKEY_FILE" ] && [ -f "$PUBKEY_FILE" ] || {
    echo "ABORT: no SSH public key found - set \$SSH_PUBKEY or create one with ssh-keygen"
    exit 1
}

echo "==> Looking for the newest Raspberry Pi OS Lite (64-bit)"
RELEASE=$(curl -sfL --max-time 60 "$INDEX/" | grep -o 'raspios_lite_arm64-[0-9-]*' | sort -u | tail -1)
[ -n "$RELEASE" ] || { echo "ABORT: could not read the release index"; exit 1; }
IMAGE=$(curl -sfL --max-time 60 "$INDEX/$RELEASE/" | grep -o '[0-9a-z_.-]*\.img\.xz' | sort -u | head -1)
[ -n "$IMAGE" ] || { echo "ABORT: no image found in $RELEASE"; exit 1; }
echo "    $IMAGE"

mkdir -p "$CACHE"
IMG="$CACHE/$IMAGE"
if [ ! -f "$IMG" ]; then
    echo "==> Downloading (about 500 MB, cached in $CACHE)"
    curl -fL --max-time 3600 -o "$IMG.part" "$INDEX/$RELEASE/$IMAGE"
    mv "$IMG.part" "$IMG"
fi

echo "==> Verifying the download"
EXPECTED=$(curl -sfL --max-time 60 "$INDEX/$RELEASE/$IMAGE.sha256" | awk '{print $1}')
ACTUAL=$(shasum -a 256 "$IMG" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "ABORT: checksum mismatch - delete $IMG and try again"
    exit 1
fi
echo "    ok - $ACTUAL"

# The image has to be written whole, so its uncompressed size decides how much
# is read back for the comparison afterwards.
IMG_SIZE=$(xz --robot -l "$IMG" | awk '/^totals/ {print $5}')
if [ $((IMG_SIZE % 1048576)) -ne 0 ]; then
    echo "ABORT: image size is not a whole number of megabytes"
    exit 1
fi

# Find the card ourselves instead of trusting a fixed diskN, which changes
# whenever the card is taken out and put back in.
echo "==> Looking for an SD card"
FOUND=""
for DEV in $(diskutil list | awk '/^\/dev\/disk[0-9]+ /{print $1}'); do
    INFO=$(diskutil info "$DEV" 2>/dev/null) || continue
    grep -q 'Protocol:  *Secure Digital' <<<"$INFO" || continue
    grep -q 'Removable Media:  *Removable' <<<"$INFO" || continue
    grep -q 'Whole:  *Yes' <<<"$INFO" || continue
    FOUND="$FOUND $DEV"
done
FOUND=${FOUND# }

if [ -z "$FOUND" ]; then
    echo "ABORT: no SD card found - is it in the reader?"
    exit 1
fi
if [ "$(wc -w <<<"$FOUND")" -gt 1 ]; then
    echo "ABORT: more than one SD card found: $FOUND"
    exit 1
fi

DISK=${FOUND##*/}
SIZE=$(diskutil info "$DISK" | sed -n 's/.*(\([0-9]*\) Bytes).*/\1/p' | head -1)
if [ "$SIZE" -gt "$MAX_SIZE" ]; then
    echo "ABORT: /dev/$DISK is $SIZE bytes - too large to be the card"
    exit 1
fi
echo "    found /dev/$DISK, removable, $((SIZE / 1000000000)) GB"

echo
echo "/dev/$DISK will be erased completely. Everything on it is gone afterwards."
diskutil list "$DISK" | sed 's/^/    /'
read -r -p "Type ERASE to continue: " CONFIRM
[ "$CONFIRM" = "ERASE" ] || { echo "Aborted."; exit 1; }

echo
read -r -p "Wifi SSID: " SSID
read -r -s -p "Wifi password (not echoed): " WIFI_PASS; echo
[ -n "$SSID" ] && [ -n "$WIFI_PASS" ] || { echo "ABORT: empty input"; exit 1; }

# Derive the PSK here so the passphrase never lands on the card.
PSK=$(WIFI_PASS="$WIFI_PASS" SSID="$SSID" python3 -c '
import hashlib, os
print(hashlib.pbkdf2_hmac("sha1", os.environ["WIFI_PASS"].encode(),
                          os.environ["SSID"].encode(), 4096, 32).hex())')
unset WIFI_PASS
if [ ${#PSK} -ne 64 ]; then
    echo "ABORT: PSK is ${#PSK} characters, expected 64 hex digits"
    exit 1
fi

echo
echo "==> Unmounting the card"
diskutil unmountDisk "/dev/$DISK"

echo "==> Writing the image (a few minutes, no progress output)"
xz -dc "$IMG" | sudo dd of="/dev/r$DISK" bs=1m

echo "==> Reading it back to verify"
# Read exactly as many whole megabytes as were written. Reading more and
# trimming with head would kill dd with SIGPIPE, which pipefail turns into a
# silent abort.
WRITTEN=$(sudo dd if="/dev/r$DISK" bs=1m count=$((IMG_SIZE / 1048576)) 2>/dev/null | shasum -a 256 | awk '{print $1}')
ORIGINAL=$(xz -dc "$IMG" | shasum -a 256 | awk '{print $1}')
if [ "$WRITTEN" != "$ORIGINAL" ]; then
    echo "ABORT: the card does not read back what was written - bad card"
    exit 1
fi
echo "    ok - $WRITTEN"

echo "==> Mounting the fresh boot partition"
diskutil mountDisk "/dev/$DISK" >/dev/null 2>&1 || true
for _ in $(seq 30); do [ -d /Volumes/bootfs ] && break; sleep 1; done
[ -d /Volumes/bootfs ] || { echo "ABORT: /Volumes/bootfs did not appear"; exit 1; }

echo "==> Writing the cloud-init user-data"
cat > /Volumes/bootfs/user-data <<EOF
#cloud-config

# Applied once on the first boot by cloud-init, NoCloud data source.

manage_resolv_conf: false

hostname: ${HOST_NAME}
manage_etc_hosts: true

apt:
  preserve_sources_list: true
  conf: |
    Acquire {
      Check-Date "false";
    };

timezone: ${TIMEZONE}
keyboard:
  model: pc105
  layout: "${KEYMAP}"

# Singular "user:" on purpose: it extends the distro's default account and
# keeps its group memberships. A plural "users:" list without "- default"
# produces an account with no groups at all.
user:
  name: ${USER_NAME}
  shell: /bin/bash
  # No password at all: SSH takes the key only, and whoever stands at the
  # console holds the machine anyway and could just read the unencrypted card.
  # A password would guard nothing and only has to be remembered.
  lock_passwd: true
  ssh_authorized_keys:
    - "$(cat "$PUBKEY_FILE")"
  sudo: ALL=(ALL) NOPASSWD:ALL

ssh_pwauth: false

runcmd:
  # cloud-init writes host keys but never starts sshd, and the image ships it
  # disabled. Without this the machine is headless and unreachable.
  - [ systemctl, enable, --now, ssh ]
  # setup.sh runs sudo over ssh non-interactively, so make that work.
  - [ sh, -c, "echo '${USER_NAME} ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/010_${USER_NAME}-nopasswd" ]
  - [ chmod, '0440', '/etc/sudoers.d/010_${USER_NAME}-nopasswd' ]
  # The image blocks the radio until a country is set. Belt and braces.
  - [ rfkill, unblock, wifi ]
  - [ sh, -c, "for f in /var/lib/systemd/rfkill/*:wlan; do echo 0 > \\"\$f\\"; done" ]
  - [ sh, -c, "nmcli radio wifi on || true" ]
  # Log in on the console without a password, since the account has none.
  # raspi-config reads the user from \$SUDO_USER, which is empty here, and it
  # writes the drop-in without creating its directory first.
  - [ mkdir, -p, "/etc/systemd/system/getty@tty1.service.d" ]
  - [ sh, -c, "SUDO_USER=${USER_NAME} raspi-config nonint do_boot_behaviour B2" ]
EOF

echo "==> Writing the cloud-init network-config"
cat > /Volumes/bootfs/network-config <<EOF
# netplan-compatible configuration, applied once on the first boot.
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      regulatory-domain: "${COUNTRY}"
      access-points:
        "${SSID}":
          password: "${PSK}"
      optional: true
EOF

sync
diskutil eject "/dev/$DISK" >/dev/null

echo
echo "==> Done. Put the card in the board; the first boot takes 15 to 20 minutes."
echo "    Then: ssh ${TARGET} 'cloud-init status --long', ./setup.sh, ./deploy.sh"

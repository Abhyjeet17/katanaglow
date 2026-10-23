#!/usr/bin/env bash
# Installs the KatanaGlow service. Run from the project folder:  sudo bash deploy/install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo:  sudo bash deploy/install.sh"; exit 1; }
if [ -z "${SUDO_USER:-}" ] || [ "$SUDO_USER" = root ]; then
    echo "Run it with sudo from your normal account (it adds that account to the katanaglow group)."
    exit 1
fi
HERE=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$HERE/katanaglow/daemon.py" ] || { echo "Run from the extracted katanaglow folder."; exit 1; }

for cmd in systemd-sysusers udevadm systemctl usermod install python3; do
    command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 1; }
done
# Some systems do not ship these folders yet
install -d -m 0755 /etc/sysusers.d /etc/udev/rules.d /etc/systemd/system /usr/local/bin

echo "1/7 creating the unprivileged 'katanaglow' system user"
install -m 0644 "$HERE/deploy/katanaglow.sysusers" /etc/sysusers.d/katanaglow.conf
systemd-sysusers /etc/sysusers.d/katanaglow.conf

echo "2/7 installing the program to /opt/katanaglow (owned by root, read-only to the service)"
install -d -m 0755 /opt/katanaglow
rm -rf /opt/katanaglow/katanaglow /opt/katanaglow/data
cp -r "$HERE/katanaglow" "$HERE/data" /opt/katanaglow/
cp "$HERE/README.md" "$HERE/LICENSE" /opt/katanaglow/
install -d -m 0755 /usr/share/doc/katanaglow
install -m 0644 "$HERE/docs/USER_GUIDE.md" "$HERE/README.md" "$HERE/LICENSE" /usr/share/doc/katanaglow/
find /opt/katanaglow -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root /opt/katanaglow
chmod -R go-w /opt/katanaglow

echo "3/7 installing the katanaglow-ctl command, the settings window and its menu entry"
cat > /usr/local/bin/katanaglow-ctl <<'WRAP'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/katanaglow exec /usr/bin/python3 -m katanaglow.ctl "$@"
WRAP
chmod 0755 /usr/local/bin/katanaglow-ctl
cat > /usr/local/bin/katanaglow-gui <<'WRAP'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/katanaglow exec /usr/bin/python3 -m katanaglow.gui "$@"
WRAP
chmod 0755 /usr/local/bin/katanaglow-gui
install -d -m 0755 /usr/share/applications
install -m 0644 "$HERE/deploy/katanaglow.desktop" /usr/share/applications/katanaglow.desktop

echo "4/7 installing the udev rule (replaces the earlier test rule of the same name)"
install -m 0644 "$HERE/deploy/70-katanaglow.rules" /etc/udev/rules.d/70-katanaglow.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --action=change
# The earlier test rule left an ACL on the device node; it blocks the new group, so clear it
for n in /sys/class/hidraw/hidraw*; do
    if grep -qi '^HID_ID=0003:00001462:00001601$' "$n/device/uevent" 2>/dev/null; then
        node="/dev/$(basename "$n")"
        setfacl -b "$node" 2>/dev/null || true
        chgrp katanaglow "$node"
        chmod 0660 "$node"
    fi
done

echo "5/7 installing the systemd service"
install -m 0644 "$HERE/deploy/katanaglow.service" /etc/systemd/system/katanaglow.service
systemctl daemon-reload

echo "6/7 adding $SUDO_USER to the katanaglow group (lets you use the control socket only)"
usermod -aG katanaglow "$SUDO_USER"

echo "7/7 starting the service and enabling it at boot"
systemctl enable katanaglow.service
systemctl restart katanaglow.service
sleep 1
systemctl --no-pager --lines=8 status katanaglow.service || true

cat <<MSG

Done. Group membership applies after you log out and back in. Until then, try:
    sg katanaglow -c 'katanaglow-ctl status'     (if 'sg' is missing: sudo apt install util-linux-extra)
User guide: /usr/share/doc/katanaglow/USER_GUIDE.md
Settings:   open "KatanaGlow" from the app menu, or run katanaglow-gui
Logs:       journalctl -u katanaglow -e
Uninstall:  sudo bash deploy/uninstall.sh   (add --purge to also delete saved settings and the user)
MSG

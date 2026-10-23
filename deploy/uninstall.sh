#!/usr/bin/env bash
# Removes the KatanaGlow service:  sudo bash deploy/uninstall.sh [--purge]
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo:  sudo bash deploy/uninstall.sh [--purge]"; exit 1; }

systemctl disable --now katanaglow.service 2>/dev/null || true
rm -f /etc/systemd/system/katanaglow.service
systemctl daemon-reload
rm -f /etc/udev/rules.d/70-katanaglow.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --action=change
rm -f /usr/local/bin/katanaglow-ctl /usr/local/bin/katanaglow-gui /usr/share/applications/katanaglow.desktop /etc/sysusers.d/katanaglow.conf
rm -rf /opt/katanaglow /usr/share/doc/katanaglow
if [ -n "${SUDO_USER:-}" ] && getent group katanaglow >/dev/null; then
    gpasswd -d "$SUDO_USER" katanaglow 2>/dev/null || true
fi
if [ "${1:-}" = "--purge" ]; then
    rm -rf /var/lib/katanaglow
    userdel katanaglow 2>/dev/null || true
    getent group katanaglow >/dev/null && groupdel katanaglow 2>/dev/null || true
    echo "Purged settings, user and group."
fi
echo "Removed. The keyboard returns to its saved lighting at the next reboot."

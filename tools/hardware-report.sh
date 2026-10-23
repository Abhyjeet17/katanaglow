#!/usr/bin/env bash
# KatanaGlow hardware report: prints only non-identifying facts about your laptop and RGB controller,
# for a compatibility report. Read-only: it sends nothing to the keyboard and needs no sudo.
#
#   bash tools/hardware-report.sh
#
# It prints the laptop model, OS and kernel version, the controller's USB IDs and HID report descriptor,
# and the GTK/Python versions. It does NOT print your username, hostname, serial numbers, UUIDs,
# network addresses or file paths. Read the output before posting it anyway.
set -u

dmi() { cat "/sys/class/dmi/id/$1" 2>/dev/null || echo "unknown"; }

echo "KatanaGlow hardware report"
echo "laptop vendor:  $(dmi sys_vendor)"
echo "laptop model:   $(dmi product_name)"
echo "kernel:         $(uname -r)"
if [ -r /etc/os-release ]; then ( . /etc/os-release; echo "distro:         ${PRETTY_NAME:-unknown}" ); fi
echo "python:         $(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo missing)"
echo "gtk4:           $(python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; print('%d.%d.%d' % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()))" 2>/dev/null || echo 'not available')"
echo

found=0
for n in /sys/class/hidraw/hidraw*; do
    [ -e "$n/device/uevent" ] || continue
    id=$(sed -n 's/^HID_ID=//p' "$n/device/uevent")
    name=$(sed -n 's/^HID_NAME=//p' "$n/device/uevent")
    case "$name" in *[Mm]ystic[Ll]ight*|*MS-15*) ;; *) continue ;; esac
    found=1
    echo "controller:     $name"
    echo "HID_ID:         $id"
    usbdev=$(dirname "$(dirname "$(readlink -f "$n/device")")")
    [ -r "$usbdev/bcdDevice" ] && echo "device release: $(cat "$usbdev/bcdDevice")"
    if [ -r "$n/device/report_descriptor" ]; then
        echo "report descriptor (hex):"
        od -An -tx1 -v "$n/device/report_descriptor" | tr -d ' \n'; echo
    fi
    echo
done
[ "$found" -eq 1 ] || echo "No MysticLight-type HID controller found (is this the right laptop?)."

echo "keyboard backlight entries in /sys/class/leds:"
ls /sys/class/leds 2>/dev/null | grep -i -E 'kbd|backlight|rgb' || echo "  (none)"
echo
echo "KatanaGlow service: $(systemctl is-active katanaglow 2>/dev/null || echo 'not installed')"

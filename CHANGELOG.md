# Changelog

## 0.3.0 (2026-10-23)

- Saved **profiles** (colours, effect, speed, brightness, ripple look; the colour balance stays global),
  in the window and with `katanaglow-ctl profile ...`
- **Resting glow** slider for the ripple background, alongside the colour tint
- **Ripple contrast** (`punch`) so ripple colours stand out over a bright resting glow
- User guide, architecture and protocol documents, hardware-report script, licence
- Removed the standalone ripple demo; the service replaces it

## 0.2.0

- Background **service** running as an unprivileged account in a systemd sandbox, started at boot, with
  persistent settings, reconnect after unplug, and re-apply after suspend and resume
- Wave and breathe effects, static colours per zone
- **Settings window** (GTK 4) and the `katanaglow-ctl` command-line tool
- Installer and uninstaller

## 0.1.0

- First prototype: verified packet layout, zone map, and a ripple demo run by hand

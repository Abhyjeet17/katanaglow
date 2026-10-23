# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting instead:
open the **Security** tab of this repository and choose **Report a vulnerability**. Include what you found,
how to reproduce it, and the version.

You can expect an acknowledgement within a few days. This is a hobby project maintained in spare time, so
fixes follow as time allows. Only the latest release is supported.

## What the design protects

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#privilege-model) for details.

- The background service runs as an unprivileged account in a systemd sandbox: no network access,
  read-only system, no home-folder access, no capabilities, and access limited to raw HID and input devices.
- The settings window and command-line tool run as the user and can only send validated settings through a
  Unix socket restricted to the `katanaglow` group. They cannot read keystrokes or open the controller.
- The service reads the keyboard only in ripple mode, turns each press into a zone number in memory, and
  discards it. Key codes are never stored, logged or exposed.
- Requests to the socket are size-limited and strictly validated; invalid input never changes settings.

## What is out of scope

- Anyone who already has root, or is a member of the `katanaglow` group, can change your keyboard lighting.
  That is the intended use of the group.
- Any process running as the `katanaglow` service account or as root could read the keyboard directly; the
  service restricts itself, but it is not protected from root.
- Attacks that need physical access to the laptop.

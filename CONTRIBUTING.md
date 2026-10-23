# Contributing

Thanks for helping. The most useful contributions, roughly in order:

1. **Hardware reports** for other laptops or the same controller, see [docs/HARDWARE.md](docs/HARDWARE.md).
2. **An ISO layout zone map** (`data/zonemap_ansi.json` is ANSI only).
3. **Verifying the controller's own effect modes** on hardware you are happy to experiment with, with the
   results written up, before any code enables them.
4. Bug fixes, documentation and tests.

## Ground rules

- **Never send unverified commands to the controller.** `katanaglow/protocol.py` enforces an allowlist of exactly
  two packet types, and a test checks that others are refused. Widening it needs evidence from real hardware,
  described in the pull request.
- **No code copied from GPL projects** (OpenRGB is GPL). Describe a protocol fact and write the code yourself.
- **Keep the privilege model.** The window and command line must stay unprivileged clients of the service.
  Nothing outside the service should read the keyboard or open the controller.
- **Key presses stay in the service.** Never store, log or transmit key codes.
- The service and command line use only the Python standard library; keep it that way.
- Keep the style simple and match the surrounding code. Add a test with every behaviour change.

## Setup and tests

```bash
git clone https://github.com/Abhyjeet17/katanaglow.git
cd katanaglow
python3 -m unittest discover -s tests -v
```

No hardware, display or root is needed. The window tests run against a stand-in for GTK, so if you change
`gui.py`, please also run the window on a real display and say so in the pull request.

## Pull requests

- One topic per pull request, with a short description of what changed and why.
- Say how you tested it, including on what hardware if the change touches the controller.
- Update [docs/](docs/) and the [changelog](CHANGELOG.md) when behaviour changes.
- **Do not include personal data** in issues or pull requests: no usernames, hostnames, serial numbers or
  full logs. `tools/hardware-report.sh` is designed to be safe to paste.

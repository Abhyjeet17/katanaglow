# Hardware compatibility and reports

## Known status

| Laptop | Controller | Reported by | Status |
|---|---|---|---|
| MSI Katana 15 B13VFK (ANSI) | MS-1565, `1462:1601` | maintainer | Verified: static colour, four zones, off, software effects, reboot restores saved lighting |

Nobody else has reported yet. Other laptops that use the same controller may well work, since other people's
notes describe the same protocol, but nothing here claims it.

## Send a hardware report

1. Run the read-only script. It needs no sudo and sends nothing to the keyboard:

   ```bash
   bash tools/hardware-report.sh
   ```

2. **Read the output before you post it.** It prints the laptop vendor and model, OS and kernel version,
   Python and GTK versions, the controller's HID ID, name, device release and report descriptor, and whether
   the service is installed. It does not print your username, hostname, serial numbers, UUIDs, network
   addresses or file paths, and the output is short enough to check by eye.
3. Open an issue with the **Hardware report** template and paste the output, plus what happened if you
   tried the install (did the colours match, did the zones light up in the order left block, centre, right block,
   numpad, did it survive a reboot).

## What helps most

- The same controller (`1462:1601`) on a different laptop: does it work unchanged?
- Different USB IDs with a name containing "MysticLight": the report descriptor tells us whether the
  protocol matches.
- ISO keyboards: the zone map in `data/zonemap_ansi.json` is ANSI only.

## What not to do

Please **do not experiment with other HID commands** on your controller to "see what happens". Other published
commands can change the controller's stored configuration, and this project deliberately never sends them.
The program refuses anything outside its allowlist for that reason.

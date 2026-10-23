# Controller protocol notes

What this project knows about the MSI MysticLight MS-1565 keyboard controller (USB `1462:1601`), and how
it knows it. Facts are labelled **observed** (seen on the maintainer's Katana 15 B13VFK) or **reported**
(from other people's published notes, not independently verified here).

## Transport

- One USB HID interface with 64-byte interrupt IN and OUT endpoints. **Observed.**
- Linux binds it to `usbhid` / `hid-generic` and exposes a `/dev/hidraw*` node. **Observed.**
- Commands are sent as **64-byte HID feature reports with report ID `0x02`**
  (the `HIDIOCSFEATURE` ioctl on the hidraw node). **Observed.**

## Report descriptor

A vendor-defined application collection (usage page `0xFF00`) that declares report IDs 1 to 8. Decoded by
hand from a hex dump, so treat it as indicative:

| Report ID | Declared reports |
|---|---|
| 1 | Feature (63 bytes), Output (63 bytes) |
| 2 | Feature (63 bytes) |
| 3 | Feature, Output, Input (63 bytes each) |
| 4 | Feature (1 byte), Output (1 byte) |
| 5, 6 | Input (1 bit), Feature (1 bit) |
| 7 | Input (1 byte), Feature (1 byte) |
| 8 | Feature, Output, Input (63 bytes each) |

This project uses only report ID 2 for writing and a feature read of ID 1 for read-back. The purpose of the
other IDs is unknown and they are never touched.

## Packets used

Byte offsets within the 64-byte report; unlisted bytes are zero.

**Zone select** (before each effect packet)

| Byte | Value |
|---|---|
| 0 | `0x02` report ID |
| 1 | `0x01` packet type: zone select |
| 2 | zone bitmask: bit 0 left block, bit 1 centre, bit 2 right block, bit 3 numpad (`0x0F` = all) |

**Effect configuration** (static colour or off)

| Byte | Value |
|---|---|
| 0 | `0x02` report ID |
| 1 | `0x02` packet type: effect |
| 2 | mode: `0` off, `1` static |
| 3 to 4 | speed, 16-bit little-endian; `600` (`58 02`) is what MSI's own software sends for steady |
| 7, 8 | `0x0F`, `0x01` as sent by MSI's software, per the published notes |
| 9 | wave direction, `0` for static |
| 10 to 13 | keyframe: time `0`, red, green, blue |
| 14 to 17 | keyframe: time `100`, same red, green, blue |

Example, static orange (`FF8800`) on all zones. Both packets are shown trimmed to their first 18 bytes:

```
02 01 0f 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
02 02 01 58 02 00 00 0f 01 00 00 ff 88 00 64 ff 88 00
```

You can regenerate these without hardware:

```bash
python3 -c "from katanaglow import protocol as p; print(p.build_effect(p.MODE_STATIC, (255,136,0))[:18].hex(' '))"
```

## Observed behaviour

- **Colour channel order is red, green, blue.** Pure red, green and blue render correctly. The LEDs are not
  colour-balanced: mixed colours and whites lean toward green and blue, hence the `gain` setting.
- **Read-back:** a feature read of report ID 1 returns the first 10 bytes of the last effect packet.
- **Volatile:** writes do not persist. After a reboot the keyboard returns to its saved lighting.
- **Timing:** about 0.4 to 0.6 ms per packet. A frame that updates all four zones is 8 packets, and a pulse
  sweep at 10, 20, 30 and 60 frames per second kept up with no late frames. This is transport timing; smooth
  appearance was judged by eye at up to 30 fps.
- **Zones:** the four bitmask values light four distinct regions, left to right: left block, centre, right
  block, numpad. Boundaries blend over about a keycap.

## Deliberately not used

- Effect modes 2 to 4 (the controller's own breathing, wave and colour cycle) are **reported** by others but
  **not verified here**, so the protocol layer refuses them.
- Other published packet types, including those described as saving to the controller's memory, loading
  from it, or resetting it, are never sent and are not documented here. The code enforces an allowlist of
  exactly the two packet types above.
- Per-key addressing is not known to exist on this controller.

## Sources

- natanalt's reverse-engineered notes for the MS-1565 controller on a Katana 15 B12V
- the LightShow project's protocol documentation
- OpenRGB, as a reference

All three were used as documentation of the packet layout. No code was copied.

## Checking your own unit

Run `tools/hardware-report.sh` (read-only) and compare the USB IDs and report descriptor with the above.
Please do not test other packet types; see [HARDWARE.md](HARDWARE.md).

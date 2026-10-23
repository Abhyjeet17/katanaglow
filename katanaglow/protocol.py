"""MS-1565 packet builders. Only documented, hardware-verified packets are allowed.

Layout from natanalt's MS-1565 notes and LightShow's PROTOCOL.md, checked on a
B13VFK: 64-byte feature reports, report ID 2.
  packet 1: zone select (bitmask)
  packet 2: effect config (here: static colour or off only)
Save-to-flash, load-from-flash, reset and every other packet ID are refused.
"""

PACKET_SIZE = 64
REPORT_ID = 0x02
PKT_ZONE_SELECT = 0x01
PKT_EFFECT = 0x02
ALLOWED_PACKET_IDS = (PKT_ZONE_SELECT, PKT_EFFECT)

MODE_OFF = 0
MODE_STATIC = 1
# Wave, breathing and colour-cycle are documented but NOT yet verified on this unit.
VERIFIED_MODES = (MODE_OFF, MODE_STATIC)

ZONE_MASKS = (1, 2, 4, 8)          # left block, centre, right block, numpad
STEADY_SPEED_CS = 600              # speed MSI's own software sends for steady


def validate_packet(pkt):
    """Raise ValueError unless pkt is an allowlisted 64-byte packet."""
    if len(pkt) != PACKET_SIZE:
        raise ValueError("packet must be exactly 64 bytes")
    if pkt[0] != REPORT_ID or pkt[1] not in ALLOWED_PACKET_IDS:
        raise ValueError("packet ID not on the allowlist")


def build_zone_select(mask):
    if not 1 <= mask <= 0x0F:
        raise ValueError("zone mask must be 1..15")
    pkt = bytearray(PACKET_SIZE)
    pkt[0], pkt[1], pkt[2] = REPORT_ID, PKT_ZONE_SELECT, mask
    return bytes(pkt)


def build_effect(mode, rgb):
    if mode not in VERIFIED_MODES:
        raise ValueError("mode not verified on this hardware yet")
    if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
        raise ValueError("rgb must be three values 0..255")
    r, g, b = rgb
    pkt = bytearray(PACKET_SIZE)
    pkt[0], pkt[1], pkt[2] = REPORT_ID, PKT_EFFECT, mode
    pkt[3] = STEADY_SPEED_CS & 0xFF
    pkt[4] = STEADY_SPEED_CS >> 8
    pkt[7], pkt[8] = 0x0F, 0x01
    pkt[10:14] = bytes((0, r, g, b))
    pkt[14:18] = bytes((100, r, g, b))
    validate_packet(pkt)
    return bytes(pkt)


def zone_update(mask, rgb):
    """Packets that set the zones in `mask` to a static colour.

    Pure black uses the documented "off" mode, which darkens fully;
    static black can leave a base glow.
    """
    rgb = tuple(rgb)
    mode = MODE_OFF if rgb == (0, 0, 0) else MODE_STATIC
    return [build_zone_select(mask), build_effect(mode, rgb)]

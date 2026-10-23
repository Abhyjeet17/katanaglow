import os
import re
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from katanaglow import device, effects, evdev_input, protocol, zonemap

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "zonemap_ansi.json")


class ProtocolTests(unittest.TestCase):
    def test_zone_select_bytes(self):
        pkt = protocol.build_zone_select(15)
        self.assertEqual(pkt[:4], bytes([2, 1, 0x0F, 0]))
        self.assertEqual(len(pkt), 64)

    def test_static_matches_documented_layout(self):
        pkt = protocol.build_effect(protocol.MODE_STATIC, (255, 136, 0))
        self.assertEqual(pkt[:18].hex(" "), "02 02 01 58 02 00 00 0f 01 00 00 ff 88 00 64 ff 88 00")

    def test_allowlist_refuses_other_packets(self):
        for bad_id in (0xA0, 0xB0, 0xFF, 0x03):
            pkt = bytearray(64)
            pkt[0], pkt[1] = 2, bad_id
            with self.assertRaises(ValueError):
                protocol.validate_packet(bytes(pkt))
        with self.assertRaises(ValueError):
            protocol.validate_packet(bytes(63))

    def test_unverified_modes_refused(self):
        for mode in (2, 3, 4):
            with self.assertRaises(ValueError):
                protocol.build_effect(mode, (0, 0, 0))

    def test_black_uses_off_mode(self):
        self.assertEqual(protocol.zone_update(1, (0, 0, 0))[1][2], protocol.MODE_OFF)
        self.assertEqual(protocol.zone_update(1, (0, 0, 1))[1][2], protocol.MODE_STATIC)

    def test_recording_device_enforces_allowlist(self):
        dev = device.RecordingDevice()
        with self.assertRaises(ValueError):
            dev.send(bytes([2, 0xA0]) + bytes(62))


class EffectsTests(unittest.TestCase):
    def test_wave_reaches_far_zone_later_and_weaker(self):
        e = effects.RippleEngine(delay=0.1, rise=0.05, decay=0.2, falloff=0.25)
        e.trigger(0, 0.0)
        lv = e.levels(0.05)
        self.assertAlmostEqual(lv[0], 1.0, places=3)
        self.assertEqual(lv[3], 0.0)
        lv = e.levels(3 * 0.1 + 0.05)            # far zone (3 steps away) just peaked
        self.assertAlmostEqual(lv[3], 0.25, places=3)

    def test_ripples_expire_and_cap(self):
        e = effects.RippleEngine(max_ripples=3)
        for i in range(10):
            e.trigger(i % 4, 0.0)
        self.assertEqual(len(e.ripples), 3)
        e.levels(e.lifetime + 1.0)
        self.assertFalse(e.active)

    def test_levels_stay_in_range_with_many_presses(self):
        e = effects.RippleEngine()
        for i in range(8):
            e.trigger(i % 4, 0.0)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in e.levels(0.06)))

    def test_painter_sends_only_changed_zones(self):
        p = effects.ZonePainter()
        self.assertEqual(len(p.frame([(0, 0, 0)] * 4)), 8)
        self.assertEqual(p.frame([(0, 0, 0)] * 4), [])
        self.assertEqual(len(p.frame([(0, 0, 0), (9, 9, 9), (0, 0, 0), (0, 0, 0)])), 2)
        p.invalidate()
        self.assertEqual(len(p.frame([(0, 0, 0)] * 4)), 8)

    def test_mix_gain(self):
        self.assertEqual(effects.mix((0, 0, 0), (200, 200, 200), 1.0, (1.0, 0.5, 0.0)), (200, 100, 0))
        self.assertEqual(effects.mix((0, 0, 0), (200, 200, 200), 0.0, (1.0, 0.5, 0.0)), (0, 0, 0))


class ColourTests(unittest.TestCase):
    def test_single_colour_render_matches_levels(self):
        e = effects.RippleEngine(delay=0.1)
        e.trigger(1, 0.0, (10, 20, 30))
        r = e.render(0.05)
        self.assertEqual([lv for lv, _ in r], e.levels(0.05))
        self.assertEqual(r[1][1], (10, 20, 30))

    def test_overlapping_ripples_blend_colours(self):
        e = effects.RippleEngine()
        e.trigger(0, 0.0, (255, 0, 0))
        e.trigger(0, 0.0, (0, 0, 255))
        level, colour = e.render(0.05)[0]
        self.assertAlmostEqual(level, 1.0)
        self.assertEqual(colour, (128, 0, 128))

    def test_palette_cycles_in_order(self):
        p = effects.PaletteCycler([(1, 0, 0), (0, 1, 0)])
        self.assertEqual([p.next() for _ in range(3)], [(1, 0, 0), (0, 1, 0), (1, 0, 0)])

    def test_rainbow_advances_and_stays_valid(self):
        r = effects.RainbowCycler(step=0.25)
        seen = [r.next() for _ in range(5)]
        self.assertEqual(seen[0], (255, 0, 0))
        self.assertEqual(seen[0], seen[4])           # full turn
        self.assertEqual(len(set(seen[:4])), 4)
        for c in seen:
            self.assertTrue(all(0 <= v <= 255 for v in c))


class ZoneMapTests(unittest.TestCase):
    def test_map_loads_with_four_nonempty_zones(self):
        m = zonemap.load_zone_map(DATA)
        self.assertEqual(set(m.values()), {0, 1, 2, 3})

    def test_known_keys(self):
        m = zonemap.load_zone_map(DATA)
        self.assertEqual(m[zonemap.KEYCODES["W"]], 0)
        self.assertEqual(m[zonemap.KEYCODES["SPACE"]], 1)
        self.assertEqual(m[zonemap.KEYCODES["ENTER"]], 2)
        self.assertEqual(m[zonemap.KEYCODES["KP5"]], 3)

    def test_keycodes_match_kernel_header(self):
        header = "/usr/include/linux/input-event-codes.h"
        if not os.path.exists(header):
            self.skipTest("kernel header not installed")
        with open(header) as f:
            text = f.read()
        for name, code in zonemap.KEYCODES.items():
            m = re.search(r"#define\s+KEY_" + re.escape(name) + r"\s+(\d+)\b", text)
            if m is None and name.isdigit():
                m = re.search(r"#define\s+KEY_" + name + r"\s+(\d+)\b", text)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1)), code, name)


class EvdevTests(unittest.TestCase):
    SAMPLE = (
        'I: Bus=0011 Vendor=0001 Product=0001 Version=ab41\n'
        'N: Name="AT Translated Set 2 keyboard"\nP: Phys=isa0060/serio0/input0\n'
        'H: Handlers=sysrq kbd event3 leds \n\n'
        'I: Bus=0003 Vendor=dead Product=beef Version=0110\n'
        'N: Name="Example USB Keyboard"\nH: Handlers=sysrq kbd event6 leds \n'
    )

    def test_parse_and_find(self):
        devs = evdev_input.parse_devices(self.SAMPLE)
        self.assertEqual(devs[0], ("AT Translated Set 2 keyboard", ["event3"]))
        self.assertEqual(devs[1][1], ["event6"])

    def test_only_presses_count(self):
        def ev(t, c, v):
            return struct.pack(evdev_input.EVENT_FORMAT, 0, 0, t, c, v)
        data = ev(1, 17, 1) + ev(1, 17, 2) + ev(1, 17, 0) + ev(0, 0, 0) + ev(1, 30, 1)
        self.assertEqual(evdev_input.key_presses(data), [17, 30])
        self.assertEqual(evdev_input.key_presses(data + b"\x01\x02"), [17, 30])


if __name__ == "__main__":
    unittest.main()

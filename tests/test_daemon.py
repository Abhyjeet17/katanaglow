import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from katanaglow import client, config, daemon, device, effects, evdev_input, zonemap


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(config.validate(config.DEFAULTS)["mode"], "ripple")

    def test_merge_rejects_bad_input(self):
        base = config.validate(config.DEFAULTS)
        for patch in ({"mode": "disco"}, {"brightness": 2}, {"speed": 0}, {"palette": []},
                      {"palette": ["GG0000"]}, {"zone_colours": ["FF0000"]}, {"gain": [1, 1]},
                      {"nonsense": 1}, {"brightness": True}, {"brightness": float("nan")}, "x"):
            with self.assertRaises(ValueError, msg=str(patch)):
                config.merge(base, patch)

    def test_merge_normalises_case(self):
        out = config.merge(config.validate(config.DEFAULTS), {"base": "aabbcc"})
        self.assertEqual(out["base"], "AABBCC")

    def test_save_load_roundtrip_and_corrupt_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            cfg = config.merge(config.validate(config.DEFAULTS), {"mode": "wave", "speed": 2})
            config.save(path, cfg)
            self.assertEqual(config.load(path), (cfg, None))
            with open(path, "w") as f:
                f.write("{not json")
            loaded, problem = config.load(path)
            self.assertEqual(loaded["mode"], "ripple")
            self.assertIsNotNone(problem)
            self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])


class ProfileConfigTests(unittest.TestCase):
    def test_names(self):
        for ok in ("Night", "Work 2", "a", "x-y_z.1"):
            self.assertEqual(config.validate_name(ok), ok)
        for bad in ("", " lead", "trail ", "../etc", "a/b", "x" * 33, "tab\t", None, 5, "-dash"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config.validate_name(bad)

    def test_profile_is_the_look_without_gain(self):
        prof = config.make_profile(config.validate(config.DEFAULTS))
        self.assertNotIn("gain", prof)
        self.assertNotIn("version", prof)
        self.assertEqual(config.validate_profile(prof), prof)
        with self.assertRaises(ValueError):
            config.validate_profile({"mode": "disco"})
        with self.assertRaises(ValueError):
            config.validate_profile({"mystery": 1})

    def test_load_profiles_drops_bad_entries_and_survives_junk(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "profiles.json")
            self.assertEqual(config.load_profiles(path), ({}, []))
            good = config.make_profile(config.validate(config.DEFAULTS))
            config.save_profiles(path, {"Good": good, "bad/name": good, "Broken": {"mode": 5}})
            profiles, problems = config.load_profiles(path)
            self.assertEqual(list(profiles), ["Good"])
            self.assertEqual(len(problems), 2)
            with open(path, "w") as f:
                f.write("[1, 2")
            self.assertEqual(config.load_profiles(path)[0], {})
            with open(path, "w") as f:
                f.write("[1, 2]")
            self.assertEqual(config.load_profiles(path)[0], {})


class LightingTests(unittest.TestCase):
    def make(self, **patch):
        l = effects.Lighting()
        l.configure(config.merge(config.validate(config.DEFAULTS), patch), 0.0)
        return l

    def test_static_uses_zone_colours_with_gain(self):
        l = self.make(mode="static", zone_colours=["FF0000", "00FF00", "0000FF", "FFFFFF"],
                      gain=[1, 0.5, 0.5])
        self.assertEqual(l.colours(0.0), [(255, 0, 0), (0, 128, 0), (0, 0, 128), (255, 128, 128)])

    def test_off_and_brightness(self):
        self.assertEqual(self.make(mode="off").colours(1.0), [(0, 0, 0)] * 4)
        l = self.make(mode="static", zone_colours=["FFFFFF"] * 4, gain=[1, 1, 1], brightness=0.5)
        self.assertEqual(l.colours(0.0)[0], (128, 128, 128))

    def test_breathe_dark_at_start_bright_at_half_period(self):
        l = self.make(mode="breathe", palette=["FF0000"], gain=[1, 1, 1])
        self.assertEqual(l.colours(0.0)[0], (0, 0, 0))
        self.assertEqual(l.colours(l.BREATHE_PERIOD / 2)[0], (255, 0, 0))

    def test_breathe_advances_through_palette(self):
        l = self.make(mode="breathe", palette=["FF0000", "0000FF"], gain=[1, 1, 1])
        p = l.BREATHE_PERIOD
        self.assertEqual(l.colours(p * 0.5)[0], (255, 0, 0))
        self.assertEqual(l.colours(p * 1.5)[0], (0, 0, 255))

    def test_wave_moves_across_zones(self):
        l = self.make(mode="wave", palette=["FF0000", "0000FF"], gain=[1, 1, 1])
        a, b = l.colours(0.0), l.colours(0.5)
        self.assertNotEqual(a, b)
        self.assertEqual(len(set(a)), 4)               # four different colours across the zones

    def test_speed_scales_period(self):
        slow = self.make(mode="breathe", palette=["FF0000"], gain=[1, 1, 1], speed=1.0)
        fast = self.make(mode="breathe", palette=["FF0000"], gain=[1, 1, 1], speed=2.0)
        self.assertEqual(fast.colours(1.0)[0], slow.colours(2.0)[0])

    def test_ripple_fires_only_in_ripple_mode(self):
        l = self.make(mode="wave")
        l.key_zone(0, 0.0)
        self.assertEqual(l.ripple.ripples, [])
        r = self.make(mode="ripple", gain=[1, 1, 1])
        self.assertEqual(r.colours(0.0), [(0, 0, 0)] * 4)
        r.key_zone(0, 0.0)
        self.assertTrue(r.animated)
        self.assertEqual(r.colours(0.05)[0], config.hex_to_rgb("FF0040"))
        r.key_zone(0, 1.0)
        self.assertEqual(r.colours(1.05)[0], config.hex_to_rgb("FFA000"))   # palette advanced

    def test_punch_zero_is_the_original_blend(self):
        l = self.make(mode="ripple", gain=[1, 1, 1], base="404040", punch=0.0, palette=["FF0000"])
        l.key_zone(0, 0.0)
        ref = effects.RippleEngine(delay=0.06, rise=0.05, decay=0.15)
        ref.trigger(0, 0.0, (255, 0, 0))
        for t in (0.05, 0.11, 0.2, 0.4):
            expected = [effects.mix((64, 64, 64), col, lv) for lv, col in ref.render(t)]
            self.assertEqual(l.colours(t), expected)

    def test_punch_makes_colour_dominate_over_white_base(self):
        def far_zone_colour(punch):
            l = self.make(mode="ripple", gain=[1, 1, 1], base="404040", punch=punch,
                          palette=["FF0000"])
            l.key_zone(0, 0.0)
            return l.colours(0.23)[3]             # farthest zone at its strongest (level 0.25)
        plain, punchy = far_zone_colour(0.0), far_zone_colour(1.0)
        self.assertGreater(punchy[0] - punchy[1], plain[0] - plain[1])   # more red over grey
        l = self.make(mode="ripple", gain=[1, 1, 1], base="404040", punch=1.0, palette=["FF0000"])
        l.key_zone(0, 0.0)
        self.assertEqual(l.colours(0.05)[0], (255, 0, 0))                # origin: pure colour
        self.assertLess(l.colours(0.05)[3][1], 0x40)                     # elsewhere the white steps back
        idle = self.make(mode="ripple", gain=[1, 1, 1], base="404040", punch=1.0)
        self.assertEqual(idle.colours(0.0), [(64, 64, 64)] * 4)          # untouched at rest

    def test_gradient_wraps(self):
        pal = [(255, 0, 0), (0, 0, 255)]
        self.assertEqual(effects.gradient(pal, 0.0), (255, 0, 0))
        self.assertEqual(effects.gradient(pal, 1.0), (255, 0, 0))
        self.assertEqual(effects.gradient([(200, 100, 0)], 0.0), (200, 100, 0))


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        os.mkdir(self.state)
        self.sock = os.path.join(self.tmp.name, "control.sock")
        self.fifo = os.path.join(self.tmp.name, "kbd")
        os.mkfifo(self.fifo)
        self.rec = device.RecordingDevice()
        self.logs = []
        self.threads = []

    def tearDown(self):
        for d, t in self.threads:
            d.stopping = True
            t.join(3)
        self.tmp.cleanup()

    def launch(self):
        d = daemon.Daemon(self.state, self.sock, device_factory=lambda: self.rec,
                          keyboard_finder=lambda: self.fifo, log=self.logs.append)
        d.start()
        t = threading.Thread(target=lambda: self._loop(d), daemon=True)
        t.start()
        self.threads.append((d, t))
        return d

    @staticmethod
    def _loop(d):
        try:
            while not d.stopping:
                d.step()
        finally:
            d.shutdown()

    def req(self, payload):
        return client.request(payload, self.sock)

    def wait(self, cond, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_set_get_and_persist_across_restart(self):
        d = self.launch()
        r = self.req({"cmd": "set", "config": {"mode": "static", "zone_colours": ["FF0000"] * 4}})
        self.assertEqual(r["config"]["mode"], "static")
        self.assertTrue(self.wait(lambda: len(self.rec.sent) >= 8))
        self.assertTrue(self.wait(lambda: os.path.exists(os.path.join(self.state, "config.json"))))
        d.stopping = True
        self.threads[0][1].join(3)
        self.rec.sent.clear()
        d2 = self.launch()
        self.assertEqual(self.req({"cmd": "get"})["config"]["mode"], "static")
        self.assertTrue(self.wait(lambda: len(self.rec.sent) >= 8))      # re-applied on start
        self.assertTrue(all(p[0] == 2 and p[1] in (1, 2) for p in self.rec.sent))

    def test_invalid_requests_are_rejected_without_changing_anything(self):
        self.launch()
        for payload in ({"cmd": "set", "config": {"mode": "disco"}},
                        {"cmd": "set", "config": {"brightness": 5}},
                        {"cmd": "set"}, {"cmd": "format_disk"}):
            with self.assertRaises(client.ClientError):
                self.req(payload)
        self.assertEqual(self.req({"cmd": "get"})["config"]["mode"], "ripple")
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.sock)
        s.sendall(b"not json\n[1,2]\n")
        s.settimeout(2)
        data = b""
        while data.count(b"\n") < 2:
            data += s.recv(4096)
        self.assertTrue(all(json.loads(l)["ok"] is False for l in data.splitlines()))
        s.close()

    def test_oversized_line_drops_client_not_daemon(self):
        self.launch()
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.sock)
        s.settimeout(2)
        try:
            s.sendall(b"x" * (daemon.MAX_LINE + 5000))
        except OSError:
            pass
        try:
            self.assertEqual(s.recv(10), b"")
        except (ConnectionResetError, socket.timeout):
            pass
        s.close()
        self.assertEqual(self.req({"cmd": "status"})["status"]["mode"], "ripple")

    def test_keys_read_only_in_ripple_mode(self):
        d = self.launch()
        wfd = os.open(self.fifo, os.O_RDWR | os.O_NONBLOCK)
        self.assertTrue(self.wait(lambda: d.keys is not None))
        self.assertIn("reading", self.req({"cmd": "status"})["status"]["keyboard"])
        self.rec.sent.clear()
        code = zonemap.KEYCODES["Q"]
        os.write(wfd, struct.pack(evdev_input.EVENT_FORMAT, 0, 0, 1, code, 1))
        self.assertTrue(self.wait(lambda: len(self.rec.sent) > 0))
        modes = {p[2] for p in self.rec.sent if p[1] == 2}
        self.assertIn(1, modes)                       # a coloured ripple was drawn
        self.req({"cmd": "set", "config": {"mode": "wave"}})
        self.assertTrue(self.wait(lambda: d.keys is None))
        self.assertEqual(self.req({"cmd": "status"})["status"]["keyboard"], "not in use")
        os.close(wfd)

    def test_device_loss_and_reconnect(self):
        class Flaky(device.RecordingDevice):
            fail = False
            def send(self, pkt, gap=0.0):
                if Flaky.fail:
                    raise OSError(19, "No such device")
                super().send(pkt)
        flaky = Flaky()
        d = daemon.Daemon(self.state, self.sock, device_factory=lambda: flaky,
                          keyboard_finder=lambda: None, log=self.logs.append)
        d.start()
        t = threading.Thread(target=lambda: self._loop(d), daemon=True)
        t.start()
        self.threads.append((d, t))
        self.req({"cmd": "set", "config": {"mode": "static"}})
        self.assertTrue(self.wait(lambda: len(flaky.sent) >= 8))
        Flaky.fail = True
        self.req({"cmd": "set", "config": {"zone_colours": ["010203"] * 4}})
        self.assertTrue(self.wait(lambda: d.dev is None))
        Flaky.fail = False
        d.device_retry_at = 0.0
        flaky.sent.clear()
        self.assertTrue(self.wait(lambda: len(flaky.sent) >= 8, timeout=4))   # fully re-sent
        self.assertTrue(self.wait(lambda: d.dev is not None))

    def test_profiles_save_load_delete_and_persist(self):
        self.launch()
        self.req({"cmd": "set", "config": {"mode": "static", "zone_colours": ["111111", "222222", "333333", "444444"],
                                           "brightness": 0.5}})
        self.assertEqual(client.save_profile("Night", self.sock), ["Night"])
        self.req({"cmd": "set", "config": {"mode": "wave", "brightness": 1.0}})
        self.assertEqual(client.save_profile("Day", self.sock), ["Day", "Night"])
        reply = client.load_profile("Night", self.sock)
        self.assertEqual(reply["config"]["mode"], "static")
        self.assertEqual(reply["config"]["zone_colours"][1], "222222")
        self.assertEqual(reply["config"]["brightness"], 0.5)
        self.assertEqual(client.delete_profile("Day", self.sock), ["Night"])
        self.assertEqual(client.profiles(self.sock), ["Night"])
        d, t = self.threads[0]
        d.stopping = True
        t.join(3)
        self.launch()
        self.assertEqual(client.profiles(self.sock), ["Night"])           # survived a restart

    def test_loading_a_profile_keeps_current_colour_balance(self):
        self.launch()
        self.req({"cmd": "set", "config": {"mode": "off"}})
        client.save_profile("Dark", self.sock)
        self.req({"cmd": "set", "config": {"mode": "wave", "gain": [0.5, 0.5, 0.5]}})
        reply = client.load_profile("Dark", self.sock)
        self.assertEqual(reply["config"]["mode"], "off")
        self.assertEqual(reply["config"]["gain"], [0.5, 0.5, 0.5])

    def test_profile_errors(self):
        self.launch()
        for payload in ({"cmd": "load_profile", "name": "Nope"}, {"cmd": "delete_profile", "name": "Nope"},
                        {"cmd": "save_profile", "name": "../x"}, {"cmd": "save_profile"},
                        {"cmd": "load_profile", "name": 5}):
            with self.assertRaises(client.ClientError, msg=str(payload)):
                self.req(payload)
        for i in range(config.MAX_PROFILES):
            client.save_profile(f"p{i}", self.sock)
        with self.assertRaises(client.ClientError):
            client.save_profile("one too many", self.sock)
        client.save_profile("p0", self.sock)                              # overwriting is still fine
        self.assertEqual(len(client.profiles(self.sock)), config.MAX_PROFILES)

    def test_ctl_profile_commands(self):
        import io
        from contextlib import redirect_stdout
        from katanaglow import ctl
        self.launch()
        def run(*args):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = ctl.main(["--socket", self.sock, *args])
            return rc, out.getvalue().strip()
        self.assertEqual(run("profiles"), (0, "(no saved profiles)"))
        self.assertEqual(run("profile", "save", "Movie"), (0, "ok: profile 'Movie' saved"))
        self.assertEqual(run("profiles"), (0, "Movie"))
        self.assertEqual(run("profile", "load", "Movie")[1], "ok: profile 'Movie' loaded")
        self.assertEqual(run("profile", "delete", "Movie")[1], "ok: profile 'Movie' deleted")

    def test_socket_permissions_and_cleanup(self):
        d = self.launch()
        self.assertEqual(oct(os.stat(self.sock).st_mode & 0o777), "0o660")
        d.stopping = True
        self.threads[0][1].join(3)
        self.assertFalse(os.path.exists(self.sock))


if __name__ == "__main__":
    unittest.main()

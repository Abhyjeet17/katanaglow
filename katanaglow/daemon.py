"""KatanaGlow daemon: owns the RGB controller, draws the effects, remembers the settings.

Runs as an unprivileged system user (see deploy/katanaglow.service). The GUI and
katanaglow-ctl only talk to it over a Unix socket and can neither read keystrokes
nor touch the hardware. Key presses are read only while the mode is "ripple",
are turned into a zone number immediately, and never leave this process or reach a log.
"""
import argparse
import copy
import json
import os
import selectors
import signal
import socket
import struct
import sys
import time

from . import config, device, effects, evdev_input, zonemap

VERSION = "0.3"
MAX_LINE = 16 * 1024
MAX_CLIENTS = 8
DEVICE_RETRY = 2.0
KEYS_RETRY = 5.0
SAVE_DELAY = 0.5
IDLE_TICK = 0.5
KEYBOARD_NAME = "AT Translated Set 2 keyboard"
DEFAULT_ZONEMAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "zonemap_ansi.json")


class _Client:
    __slots__ = ("sock", "buf", "uid")

    def __init__(self, sock):
        self.sock, self.buf = sock, b""
        try:
            self.uid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                           struct.calcsize("3i")))[1]
        except OSError:
            self.uid = -1


class Daemon:
    def __init__(self, state_dir, sock_path, device_factory=None, keyboard_finder=None,
                 zonemap_path=DEFAULT_ZONEMAP, log=None):
        self.state_dir, self.sock_path = state_dir, sock_path
        self.cfg_path = os.path.join(state_dir, "config.json")
        self.profiles_path = os.path.join(state_dir, "profiles.json")
        self.profiles = {}
        self.device_factory = device_factory or device.HidrawDevice
        self.keyboard_finder = keyboard_finder or (lambda: evdev_input.find_event_node(KEYBOARD_NAME))
        self.zonemap_path = zonemap_path
        self.log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
        self.sel = selectors.DefaultSelector()
        self.clients = set()
        self.listener = None
        self.lighting = effects.Lighting()
        self.painter = effects.ZonePainter()
        self.cfg = None
        self.zone_of = {}
        self.dev, self.device_error, self.device_retry_at = None, None, 0.0
        self.keys, self.key_status, self.keys_retry_at = None, "not in use", 0.0
        self.next_frame = 0.0
        self.dirty_since = None
        self.stopping = False
        self._last_mono = time.monotonic()
        self._last_boot = time.clock_gettime(time.CLOCK_BOOTTIME)
        self._resend_at = None

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        self.cfg, problem = config.load(self.cfg_path)
        if problem:
            self.log(problem)
        self.profiles, problems = config.load_profiles(self.profiles_path)
        for problem in problems:
            self.log(problem)
        self.lighting.configure(self.cfg, time.monotonic())
        self.zone_of = zonemap.load_zone_map(self.zonemap_path)
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.sock_path)
        os.chmod(self.sock_path, 0o660)
        self.listener.listen(MAX_CLIENTS)
        self.listener.setblocking(False)
        self.sel.register(self.listener, selectors.EVENT_READ, "listen")
        self.log(f"katanaglow {VERSION} started, mode {self.cfg['mode']}")

    def run(self):
        self.start()
        try:
            while not self.stopping:
                self.step()
        finally:
            self.shutdown()

    def shutdown(self):
        if self.dirty_since is not None:
            self._save(time.monotonic())
        for c in list(self.clients):
            self._drop(c)
        self._close_keys("not in use")
        if self.listener:
            self.sel.unregister(self.listener)
            self.listener.close()
            try:
                os.unlink(self.sock_path)
            except OSError:
                pass
        if self.dev:
            self.dev.close()
        self.sel.close()

    # ---- one loop iteration ---------------------------------------------
    def step(self):
        now = time.monotonic()
        self._check_resume(now)
        self._ensure_device(now)
        self._ensure_keys(now)
        timeout = max(0.0, self.next_frame - now) if self.lighting.animated else IDLE_TICK
        if self.dirty_since is not None:
            timeout = min(timeout, max(0.0, self.dirty_since + SAVE_DELAY - now))
        for key, _ in self.sel.select(timeout):
            if key.data == "listen":
                self._accept()
            elif key.data == "keys":
                self._read_keys()
            else:
                self._client_read(key.data)
        now = time.monotonic()
        self._tick(now)
        if self.dirty_since is not None and now >= self.dirty_since + SAVE_DELAY:
            self._save(now)

    # ---- device ----------------------------------------------------------
    def _ensure_device(self, now):
        if self.dev is not None or now < self.device_retry_at:
            return
        try:
            self.dev = self.device_factory()
            self.device_error = None
            self.painter.invalidate()
            self.next_frame = 0.0
            self.log("RGB controller connected")
        except OSError as e:
            if str(e) != self.device_error:
                self.log(f"RGB controller unavailable: {e}")
            self.device_error = str(e)
            self.device_retry_at = now + DEVICE_RETRY

    def _drop_device(self, now, err):
        self.log(f"RGB controller lost ({err}); will retry")
        try:
            self.dev.close()
        except OSError:
            pass
        self.dev, self.device_retry_at = None, now + DEVICE_RETRY

    def _check_resume(self, now):
        """Suspend freezes CLOCK_MONOTONIC but not CLOCK_BOOTTIME; a gap means we slept."""
        boot = time.clock_gettime(time.CLOCK_BOOTTIME)
        if (boot - self._last_boot) - (now - self._last_mono) > 2.0:
            self.log("resume detected; re-applying lighting")
            self.painter.invalidate()
            self.next_frame = 0.0
            self._resend_at = now + 1.5          # firmware may reload its own lighting late
        self._last_mono, self._last_boot = now, boot
        if self._resend_at is not None and now >= self._resend_at:
            self.painter.invalidate()
            self.next_frame = 0.0
            self._resend_at = None

    def _tick(self, now):
        if now < self.next_frame:
            return
        packets = self.painter.frame(self.lighting.colours(now))
        if packets and self.dev is not None:
            try:
                self.dev.send_all(packets)
            except OSError as e:
                self._drop_device(now, e)
        self.next_frame = now + (1.0 / self.lighting.fps if self.lighting.animated else IDLE_TICK)

    # ---- keyboard (ripple mode only) -------------------------------------
    def _ensure_keys(self, now):
        want = self.cfg["mode"] == "ripple"
        if want and self.keys is None and now >= self.keys_retry_at:
            path = self.keyboard_finder()
            if path is None:
                self.key_status = "keyboard not found"
            else:
                try:
                    self.keys = evdev_input.KeyReader(path)
                    self.sel.register(self.keys, selectors.EVENT_READ, "keys")
                    self.key_status = "reading (zone numbers only)"
                    return
                except OSError as e:
                    self.key_status = f"cannot read keyboard: {e}"
            self.keys_retry_at = now + KEYS_RETRY
        elif not want and self.keys is not None:
            self._close_keys("not in use")

    def _close_keys(self, status):
        if self.keys is not None:
            try:
                self.sel.unregister(self.keys)
            except (KeyError, ValueError):
                pass
            self.keys.close()
            self.keys = None
        self.key_status = status

    def _read_keys(self):
        try:
            presses = self.keys.read_presses()
        except OSError:
            self._close_keys("keyboard read failed")
            self.keys_retry_at = time.monotonic() + KEYS_RETRY
            return
        now = time.monotonic()
        for code in presses:                      # codes are never stored or logged
            zone = self.zone_of.get(code)
            if zone is not None:
                if not self.lighting.animated:
                    self.next_frame = 0.0
                self.lighting.key_zone(zone, now)

    # ---- control socket --------------------------------------------------
    def _accept(self):
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        if len(self.clients) >= MAX_CLIENTS:
            conn.close()
            return
        conn.setblocking(False)
        c = _Client(conn)
        self.clients.add(c)
        self.sel.register(conn, selectors.EVENT_READ, c)

    def _drop(self, c):
        self.clients.discard(c)
        try:
            self.sel.unregister(c.sock)
        except (KeyError, ValueError):
            pass
        c.sock.close()

    def _client_read(self, c):
        try:
            data = c.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError:
            return self._drop(c)
        if not data:
            return self._drop(c)
        c.buf += data
        while b"\n" in c.buf:
            line, c.buf = c.buf.split(b"\n", 1)
            if not self._reply(c, self._handle(line, c.uid)):
                return
        if len(c.buf) > MAX_LINE:
            self._drop(c)

    def _reply(self, c, obj):
        try:
            c.sock.send(json.dumps(obj).encode() + b"\n")
            return True
        except OSError:
            self._drop(c)
            return False

    def status(self):
        return {"version": VERSION, "mode": self.cfg["mode"],
                "device": "connected" if self.dev else f"not connected ({self.device_error})",
                "keyboard": self.key_status}

    def _handle(self, line, uid):
        if len(line) > MAX_LINE:
            return {"ok": False, "error": "request too large"}
        try:
            req = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "invalid JSON"}
        if not isinstance(req, dict):
            return {"ok": False, "error": "request must be an object"}
        cmd = req.get("cmd")
        if cmd == "get":
            return {"ok": True, "config": self.cfg, "status": self.status()}
        if cmd == "status":
            return {"ok": True, "status": self.status()}
        if cmd == "set":
            try:
                merged = config.merge(self.cfg, req.get("config"))
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            self._apply(merged, uid)
            return {"ok": True, "config": self.cfg, "status": self.status()}
        if cmd == "profiles":
            return {"ok": True, "profiles": sorted(self.profiles)}
        if cmd in ("save_profile", "load_profile", "delete_profile"):
            return self._profile_command(cmd, req.get("name"), uid)
        return {"ok": False, "error": "unknown command"}

    def _apply(self, merged, uid):
        now = time.monotonic()
        if merged["mode"] != self.cfg["mode"]:
            self.log(f"mode {self.cfg['mode']} -> {merged['mode']} (requested by uid {uid})")
        self.cfg = merged
        self.lighting.configure(merged, now)
        self.next_frame = 0.0
        self.dirty_since = now

    def _profile_command(self, cmd, name, uid):
        try:
            name = config.validate_name(name)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if cmd == "load_profile":
            if name not in self.profiles:
                return {"ok": False, "error": f"no profile named {name!r}"}
            try:
                self._apply(config.merge(self.cfg, self.profiles[name]), uid)
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            self.log(f"profile {name!r} loaded (requested by uid {uid})")
            return {"ok": True, "config": self.cfg, "profiles": sorted(self.profiles)}
        before = dict(self.profiles)
        if cmd == "save_profile":
            if name not in self.profiles and len(self.profiles) >= config.MAX_PROFILES:
                return {"ok": False, "error": f"at most {config.MAX_PROFILES} profiles"}
            self.profiles[name] = copy.deepcopy(config.make_profile(self.cfg))
        else:                                              # delete_profile
            if name not in self.profiles:
                return {"ok": False, "error": f"no profile named {name!r}"}
            del self.profiles[name]
        try:
            config.save_profiles(self.profiles_path, self.profiles)
        except OSError as e:
            self.profiles = before
            self.log(f"could not save profiles: {e}")
            return {"ok": False, "error": "could not save profiles"}
        return {"ok": True, "profiles": sorted(self.profiles)}

    def _save(self, now):
        try:
            config.save(self.cfg_path, self.cfg)
            self.dirty_since = None
        except OSError as e:
            self.log(f"could not save settings: {e}")
            self.dirty_since = now + 10.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-dir", default=os.environ.get("STATE_DIRECTORY", "/var/lib/katanaglow"))
    runtime = os.environ.get("RUNTIME_DIRECTORY", "/run/katanaglow")
    ap.add_argument("--socket", default=os.path.join(runtime, "control.sock"))
    args = ap.parse_args(argv)
    d = Daemon(args.state_dir, args.socket)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: setattr(d, "stopping", True))
    d.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

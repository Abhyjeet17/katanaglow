"""Read key presses from one keyboard's evdev node, read-only.

Privacy: this module never grabs the device (typing is unaffected) and hands back
only key codes for the caller to turn into zone numbers immediately. Nothing is
stored or logged here.
"""
import os
import struct

EVENT_FORMAT = "llHHi"                 # struct input_event on 64-bit Linux
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
EV_KEY = 1
KEY_PRESS = 1                          # 0 = release, 2 = auto-repeat (both ignored)


def parse_devices(text):
    """Parse /proc/bus/input/devices into [(name, [event nodes])]."""
    found = []
    for block in text.strip().split("\n\n"):
        name, nodes = None, []
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("H: Handlers="):
                nodes = [t for t in line.split("=", 1)[1].split() if t.startswith("event")]
        if name is not None:
            found.append((name, nodes))
    return found


def find_event_node(name="AT Translated Set 2 keyboard", devices_file="/proc/bus/input/devices"):
    """Look the keyboard up by name; event numbers can change between boots."""
    with open(devices_file) as f:
        for dev_name, nodes in parse_devices(f.read()):
            if dev_name == name and nodes:
                return "/dev/input/" + nodes[0]
    return None


def key_presses(data):
    """Key codes of press events in a raw chunk of input_event structs."""
    codes = []
    usable = len(data) - len(data) % EVENT_SIZE
    for off in range(0, usable, EVENT_SIZE):
        _s, _us, etype, code, value = struct.unpack_from(EVENT_FORMAT, data, off)
        if etype == EV_KEY and value == KEY_PRESS:
            codes.append(code)
    return codes


class KeyReader:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def fileno(self):
        return self.fd

    def read_presses(self):
        try:
            return key_presses(os.read(self.fd, EVENT_SIZE * 64))
        except BlockingIOError:
            return []

    def close(self):
        os.close(self.fd)

"""Transport. HidrawDevice talks to the real controller; RecordingDevice is a test double."""
import fcntl
import os
import time

from . import protocol

HID_ID = "0003:00001462:00001601"
_HIDIOCSFEATURE_64 = (3 << 30) | (protocol.PACKET_SIZE << 16) | (ord("H") << 8) | 0x06


def find_hidraw(sysfs="/sys/class/hidraw"):
    """Find the controller by HID_ID, never by a hardcoded hidraw number."""
    try:
        names = sorted(os.listdir(sysfs))
    except OSError:
        return None
    for name in names:
        try:
            with open(os.path.join(sysfs, name, "device", "uevent")) as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith("HID_ID=") and line[7:].upper() == HID_ID:
                return "/dev/" + name
    return None


class HidrawDevice:
    def __init__(self, path=None):
        path = path or find_hidraw()
        if path is None:
            raise FileNotFoundError(f"no controller with HID_ID {HID_ID}")
        self.path = path
        self.fd = os.open(path, os.O_RDWR)

    def send(self, pkt, gap=0.0):
        protocol.validate_packet(pkt)
        fcntl.ioctl(self.fd, _HIDIOCSFEATURE_64, pkt)
        if gap:
            time.sleep(gap)

    def send_all(self, packets):
        for pkt in packets:
            self.send(pkt)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class RecordingDevice:
    """No hardware: remembers what would have been sent."""

    def __init__(self):
        self.sent = []

    def send(self, pkt, gap=0.0):
        protocol.validate_packet(pkt)
        self.sent.append(bytes(pkt))

    def send_all(self, packets):
        for pkt in packets:
            self.send(pkt)

    def close(self):
        pass

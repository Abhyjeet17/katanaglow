"""Pure effects code: no hardware, no clock reads. Time is always passed in."""
import colorsys
import math

from . import config, protocol


class RippleEngine:
    """A pulse that spreads outward from the zone of a key press.

    Zones are 0..zone_count-1, left to right. Resolution is four columns,
    so this is a coarse ripple, not a per-key one. Every ripple carries its
    own colour; where ripples overlap, their colours are blended by strength.
    """

    def __init__(self, zone_count=4, delay=0.06, rise=0.05, decay=0.15,
                 falloff=0.25, max_ripples=8):
        if rise <= 0 or decay <= 0 or delay < 0:
            raise ValueError("rise and decay must be positive, delay non-negative")
        self.zone_count = zone_count
        self.delay, self.rise, self.decay = delay, rise, decay
        self.falloff = falloff
        self.max_ripples = max_ripples
        self.ripples = []                      # (origin_zone, start_time, colour)

    @property
    def lifetime(self):
        return (self.zone_count - 1) * self.delay + self.rise + 5 * self.decay

    @property
    def active(self):
        return bool(self.ripples)

    def trigger(self, zone, now, colour=(255, 255, 255)):
        if not 0 <= zone < self.zone_count:
            return
        self.ripples.append((zone, now, tuple(colour)))
        if len(self.ripples) > self.max_ripples:      # drop the oldest
            self.ripples = self.ripples[-self.max_ripples:]

    def render(self, now):
        """Per zone: (level 0..1, blended ripple colour). Colour is (0,0,0) when level is 0."""
        self.ripples = [r for r in self.ripples if now - r[1] <= self.lifetime]
        n = self.zone_count
        weight = [0.0] * n
        csum = [[0.0, 0.0, 0.0] for _ in range(n)]
        for origin, t0, colour in self.ripples:
            for z in range(n):
                d = abs(z - origin)
                age = now - t0 - d * self.delay
                if age < 0:
                    continue
                amp = max(0.0, 1.0 - d * self.falloff)
                env = age / self.rise if age < self.rise else math.exp(-(age - self.rise) / self.decay)
                c = amp * env
                if c <= 0:
                    continue
                weight[z] += c
                for i in range(3):
                    csum[z][i] += c * colour[i]
        out = []
        for z in range(n):
            w = weight[z]
            if w <= 0:
                out.append((0.0, (0, 0, 0)))
            else:
                out.append((min(1.0, w), tuple(min(255, round(v / w)) for v in csum[z])))
        return out

    def levels(self, now):
        return [lv for lv, _ in self.render(now)]


class PaletteCycler:
    """Hands out the palette's colours in order, one per key press."""

    def __init__(self, colours):
        if not colours:
            raise ValueError("palette must not be empty")
        self.colours = [tuple(c) for c in colours]
        self.i = 0

    def next(self):
        colour = self.colours[self.i % len(self.colours)]
        self.i += 1
        return colour


class RainbowCycler:
    """Walks around the colour wheel by `step` (0..1 of a full turn) per key press."""

    def __init__(self, step=0.07, hue=0.0):
        self.step, self.hue = step, hue % 1.0

    def next(self):
        r, g, b = colorsys.hsv_to_rgb(self.hue, 1.0, 1.0)
        self.hue = (self.hue + self.step) % 1.0
        return (round(r * 255), round(g * 255), round(b * 255))


def mix(base, peak, level, gain=(1.0, 1.0, 1.0)):
    """Blend base to peak by level (0..1), then apply per-channel gain (colour balance)."""
    return tuple(
        min(255, max(0, round((b + (p - b) * level) * g)))
        for b, p, g in zip(base, peak, gain)
    )


class ZonePainter:
    """Turns per-zone colours into packets, sending only zones whose colour changed."""

    def __init__(self, masks=protocol.ZONE_MASKS):
        self.masks = masks
        self.last = {}

    def frame(self, colours):
        packets = []
        for mask, rgb in zip(self.masks, colours):
            rgb = tuple(rgb)
            if self.last.get(mask) == rgb:
                continue
            packets.extend(protocol.zone_update(mask, rgb))
            self.last[mask] = rgb
        return packets

    def invalidate(self):
        """Forget what was sent (e.g. after the device was reconnected)."""
        self.last.clear()


def scale(rgb, gain, brightness):
    """Colour balance (per-channel gain) and brightness, rounded to 0..255."""
    return tuple(min(255, max(0, round(c * g * brightness))) for c, g in zip(rgb, gain))


def gradient(palette, pos):
    """Smooth, wrapping colour at position pos (0..1) around the palette.

    A one-colour palette fades to black and back, so a wave is still visible.
    """
    pts = list(palette) if len(palette) > 1 else [palette[0], (0, 0, 0)]
    n = len(pts)
    x = (pos % 1.0) * n
    i = int(x) % n
    f = x - int(x)
    s = (1 - math.cos(math.pi * f)) / 2
    a, b = pts[i], pts[(i + 1) % n]
    return tuple(round(a[k] + (b[k] - a[k]) * s) for k in range(3))


class Lighting:
    """Everything the daemon draws: one object that turns settings plus time into 4 colours."""

    WAVE_PERIOD = 3.0          # seconds per cycle at speed 1.0
    BREATHE_PERIOD = 4.0

    def __init__(self, zone_count=config.ZONES):
        self.zone_count = zone_count
        self.cfg = None
        self.t0 = 0.0
        self.palette = []
        self.picker = None
        self.ripple = None

    def configure(self, cfg, now):
        old = self.cfg
        if old is None or old["mode"] != cfg["mode"]:
            self.t0 = now
        if old is None or old["speed"] != cfg["speed"]:
            sp = cfg["speed"]
            self.ripple = RippleEngine(zone_count=self.zone_count, delay=0.06 / sp,
                                       rise=0.05 / sp, decay=0.15 / sp)
        elif old["mode"] != cfg["mode"]:
            self.ripple.ripples.clear()
        self.palette = [config.hex_to_rgb(h) for h in cfg["palette"]]
        if old is None or old["palette"] != cfg["palette"]:
            self.picker = PaletteCycler(self.palette)
        self.cfg = cfg

    def key_zone(self, zone, now):
        if self.cfg["mode"] == "ripple":
            self.ripple.trigger(zone, now, self.picker.next())

    @property
    def animated(self):
        mode = self.cfg["mode"]
        return mode in ("wave", "breathe") or (mode == "ripple" and self.ripple.active)

    @property
    def fps(self):
        return 30 if self.cfg["mode"] == "ripple" else 20

    def colours(self, now):
        cfg, mode, n = self.cfg, self.cfg["mode"], self.zone_count
        if mode == "off":
            return [(0, 0, 0)] * n
        if mode == "static":
            raw = [config.hex_to_rgb(h) for h in cfg["zone_colours"]]
        elif mode == "breathe":
            t = (now - self.t0) / (self.BREATHE_PERIOD / cfg["speed"])
            colour = self.palette[int(t) % len(self.palette)]
            level = 0.5 * (1 - math.cos(2 * math.pi * (t - int(t))))
            raw = [tuple(round(c * level) for c in colour)] * n
        elif mode == "wave":
            t = (now - self.t0) / (self.WAVE_PERIOD / cfg["speed"])
            raw = [gradient(self.palette, z / n - t) for z in range(n)]
        else:                                           # ripple
            base = config.hex_to_rgb(cfg["base"])
            rendered = self.ripple.render(now)
            punch = cfg["punch"]
            # Contrast over a bright resting colour: the ripple colour takes over sooner (a
            # level of 0.25 counts as 0.5 at full punch), and while any ripple is passing the
            # resting colour steps back to 30%, so the colour stands out. punch 0 (the default)
            # gives the original blend exactly.
            weights = [lv ** (1.0 - 0.5 * punch) for lv, _ in rendered]
            dip = 1.0 - 0.7 * punch * max(weights)
            dipped = tuple(round(c * dip) for c in base)
            raw = [mix(dipped, col, w) for w, (_, col) in zip(weights, rendered)]
        return [scale(c, cfg["gain"], cfg["brightness"]) for c in raw]

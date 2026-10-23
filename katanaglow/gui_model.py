"""GUI logic that needs no display: colour conversion, which controls show, palette rules,
and a queue that merges rapid slider/colour changes into one request."""

MODES = (("off", "Off"), ("static", "Static"), ("wave", "Wave"),
         ("breathe", "Breathe"), ("ripple", "Ripple"))
ZONE_NAMES = ("Left block", "Centre", "Right block", "Numpad")
EFFECT_MODES = ("wave", "breathe", "ripple")
PALETTE_MIN, PALETTE_MAX = 1, 8
NEW_COLOURS = ("FF0040", "FFA000", "00FF60", "00A0FF", "A000FF", "FFFF00", "FF00FF", "00FFFF")


def rgba_to_hex(r, g, b):
    """Floats 0..1 to 'RRGGBB', clamped."""
    return "".join("%02X" % min(255, max(0, round(c * 255))) for c in (r, g, b))


def hex_to_floats(text):
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


def glow_to_hex(percent):
    """Resting-glow slider (0..100) to a grey. LEDs look brighter than the numbers suggest, so the
    slider is squared: the low end, where dim whites live, gets fine control."""
    level = min(1.0, max(0.0, percent / 100.0)) ** 2
    return "%02X" % round(255 * level) * 3


def hex_to_glow(text):
    """Inverse of glow_to_hex, using the brightest channel (so a tinted base still shows a sensible value)."""
    peak = max(int(text[i:i + 2], 16) for i in (0, 2, 4))
    return 100.0 * (peak / 255.0) ** 0.5


def visible_sections(mode):
    """Which optional parts of the window apply to a mode."""
    out = set()
    if mode == "static":
        out.add("zones")
    if mode in EFFECT_MODES:
        out.update(("palette", "speed"))
    if mode == "ripple":
        out.add("base")
    return out


def add_colour(palette):
    if len(palette) >= PALETTE_MAX:
        return list(palette)
    fresh = next((c for c in NEW_COLOURS if c not in palette), palette[-1])
    return list(palette) + [fresh]


def remove_colour(palette):
    return list(palette[:-1]) if len(palette) > PALETTE_MIN else list(palette)


class PatchQueue:
    """Collects changes made in quick succession and sends them as one patch."""

    def __init__(self, send, schedule, cancel, on_error=None, delay_ms=120):
        self._send, self._schedule, self._cancel = send, schedule, cancel
        self._on_error, self.delay_ms = on_error, delay_ms
        self._pending, self._handle = {}, None

    @property
    def pending(self):
        return bool(self._pending)

    def add(self, **patch):
        self._pending.update(patch)
        if self._handle is None:
            self._handle = self._schedule(self.delay_ms, self._fire)

    def _fire(self):
        self._handle = None
        self.flush_now()
        return False                      # one-shot timer

    def flush_now(self):
        if self._handle is not None:
            self._cancel(self._handle)
            self._handle = None
        if not self._pending:
            return
        patch, self._pending = self._pending, {}
        try:
            self._send(patch)
        except Exception as e:            # report, never crash the window
            if self._on_error is None:
                raise
            self._on_error(str(e))

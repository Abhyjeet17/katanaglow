"""Settings model: validation and persistence. The daemon owns the one true copy."""
import json
import math
import os
import re
import tempfile

MODES = ("static", "wave", "breathe", "ripple", "off")
_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")

DEFAULTS = {
    "version": 1,
    "mode": "ripple",
    "brightness": 1.0,                       # 0..1, software scaling
    "speed": 1.0,                            # 0.25..4, effect speed multiplier
    "zone_colours": ["FF0040", "FFA000", "00FF60", "00A0FF"],   # static mode, left to right
    "palette": ["FF0040", "FFA000", "00FF60", "00A0FF", "A000FF"],  # wave, breathe, ripple
    "base": "000000",                        # ripple resting colour
    "punch": 0.0,                            # 0..1 ripple contrast over a non-black base
    "gain": [1.0, 0.8, 0.7],                 # colour balance R,G,B (tuned by eye)
}
ZONES = 4


def hex_to_rgb(text):
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _hex(value, what):
    if not isinstance(value, str) or not _HEX.match(value):
        raise ValueError(f"{what}: expected 6 hex digits like FF8800")
    return value.upper()


def _num(value, lo, hi, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what}: expected a number")
    if not lo <= value <= hi:
        raise ValueError(f"{what}: must be between {lo} and {hi}")
    return float(value)


def validate(cfg):
    """Return a cleaned copy of cfg or raise ValueError. Unknown or missing keys are errors."""
    if not isinstance(cfg, dict):
        raise ValueError("settings must be an object")
    if set(cfg) != set(DEFAULTS):
        raise ValueError("unknown or missing setting names: " + ", ".join(sorted(set(cfg) ^ set(DEFAULTS))))
    if cfg["version"] != 1:
        raise ValueError("unsupported settings version")
    if cfg["mode"] not in MODES:
        raise ValueError("mode must be one of " + ", ".join(MODES))
    zc = cfg["zone_colours"]
    if not isinstance(zc, list) or len(zc) != ZONES:
        raise ValueError(f"zone_colours: need exactly {ZONES} colours")
    pal = cfg["palette"]
    if not isinstance(pal, list) or not 1 <= len(pal) <= 8:
        raise ValueError("palette: need 1 to 8 colours")
    gain = cfg["gain"]
    if not isinstance(gain, list) or len(gain) != 3:
        raise ValueError("gain: need three numbers (R, G, B)")
    return {
        "version": 1,
        "mode": cfg["mode"],
        "brightness": _num(cfg["brightness"], 0.0, 1.0, "brightness"),
        "speed": _num(cfg["speed"], 0.25, 4.0, "speed"),
        "zone_colours": [_hex(c, "zone_colours") for c in zc],
        "palette": [_hex(c, "palette") for c in pal],
        "base": _hex(cfg["base"], "base"),
        "punch": _num(cfg["punch"], 0.0, 1.0, "punch"),
        "gain": [_num(g, 0.0, 1.0, "gain") for g in gain],
    }


def merge(current, patch):
    """Apply a partial update to a valid config; the result is validated."""
    if not isinstance(patch, dict):
        raise ValueError("config patch must be an object")
    new = dict(current)
    new.update(patch)
    return validate(new)


def load(path):
    """Return (config, problem). A missing file is normal; a bad one falls back to defaults."""
    try:
        with open(path) as f:
            data = json.load(f)
        return validate({**DEFAULTS, **data}), None
    except FileNotFoundError:
        return validate(DEFAULTS), None
    except (OSError, ValueError) as e:
        return validate(DEFAULTS), f"could not use saved settings ({e}); using defaults"


def _write_json_atomic(path, obj):
    """Temp file in the same folder, then rename, so a crash never leaves half a file."""
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path, cfg):
    _write_json_atomic(path, cfg)


# ---- profiles: named presets of the look (the colour balance stays global) ----
PROFILE_KEYS = tuple(k for k in DEFAULTS if k not in ("version", "gain"))
MAX_PROFILES = 20
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,31}$")


def validate_name(name):
    if not isinstance(name, str) or not _NAME.match(name) or name != name.strip():
        raise ValueError("profile name: 1 to 32 letters, digits, spaces, _ . or -")
    return name


def make_profile(cfg):
    return {k: cfg[k] for k in PROFILE_KEYS}


def validate_profile(data):
    """A profile is the look only; anything missing falls back to the defaults."""
    if not isinstance(data, dict):
        raise ValueError("profile must be an object")
    full = validate({**DEFAULTS, **data})
    return make_profile(full)


def load_profiles(path):
    """Return ({name: profile}, [problems]). Bad entries are dropped, never fatal."""
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError):
        return {}, ["could not read saved profiles; starting with none"]
    if not isinstance(raw, dict):
        return {}, ["saved profiles file is not valid; starting with none"]
    out, problems = {}, []
    for name in sorted(raw):
        try:
            out[validate_name(name)] = validate_profile(raw[name])
        except ValueError:
            problems.append(f"ignored an invalid saved profile {name!r}")
    if len(out) > MAX_PROFILES:
        out = {n: out[n] for n in sorted(out)[:MAX_PROFILES]}
        problems.append("too many saved profiles; kept the first %d" % MAX_PROFILES)
    return out, problems


def save_profiles(path, profiles):
    _write_json_atomic(path, profiles)

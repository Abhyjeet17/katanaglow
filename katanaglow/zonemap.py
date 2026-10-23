"""Key to zone map. The zone data lives in data/zonemap_ansi.json so it is easy to correct."""
import json

# Linux input keycodes (linux/input-event-codes.h); tests check these against the header.
KEYCODES = {
    "ESC": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "MINUS": 12, "EQUAL": 13, "BACKSPACE": 14, "TAB": 15,
    "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23, "O": 24, "P": 25,
    "LEFTBRACE": 26, "RIGHTBRACE": 27, "ENTER": 28, "LEFTCTRL": 29,
    "A": 30, "S": 31, "D": 32, "F": 33, "G": 34, "H": 35, "J": 36, "K": 37, "L": 38,
    "SEMICOLON": 39, "APOSTROPHE": 40, "GRAVE": 41, "LEFTSHIFT": 42, "BACKSLASH": 43,
    "Z": 44, "X": 45, "C": 46, "V": 47, "B": 48, "N": 49, "M": 50,
    "COMMA": 51, "DOT": 52, "SLASH": 53, "RIGHTSHIFT": 54, "KPASTERISK": 55, "LEFTALT": 56,
    "SPACE": 57, "CAPSLOCK": 58,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63, "F6": 64, "F7": 65, "F8": 66,
    "F9": 67, "F10": 68, "NUMLOCK": 69,
    "KP7": 71, "KP8": 72, "KP9": 73, "KPMINUS": 74, "KP4": 75, "KP5": 76, "KP6": 77,
    "KPPLUS": 78, "KP1": 79, "KP2": 80, "KP3": 81, "KP0": 82, "KPDOT": 83,
    "102ND": 86, "F11": 87, "F12": 88, "KPENTER": 96, "RIGHTCTRL": 97, "KPSLASH": 98,
    "SYSRQ": 99, "RIGHTALT": 100, "HOME": 102, "UP": 103, "PAGEUP": 104, "LEFT": 105,
    "RIGHT": 106, "END": 107, "DOWN": 108, "PAGEDOWN": 109, "INSERT": 110, "DELETE": 111,
    "LEFTMETA": 125, "RIGHTMETA": 126, "COMPOSE": 127, "F23": 193,
}


def load_zone_map(path):
    """Return {keycode: zone_index} where zone_index 0..3 matches protocol.ZONE_MASKS."""
    with open(path) as f:
        data = json.load(f)
    mapping = {}
    for zone, names in enumerate(data["zones"]):
        for name in names:
            code = KEYCODES[name]            # KeyError on a typo is deliberate
            if code in mapping:
                raise ValueError(f"key {name} appears in more than one zone")
            mapping[code] = zone
    return mapping

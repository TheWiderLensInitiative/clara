"""Clara's look: a small style spec the app renders (see the app's CharacterStyle). Stored on the PC so Clara can restyle
herself and every phone updates instantly. Everything is validated; unknown values fall back to her original look."""
import re

DEFAULT = {"body": ["#58DBFB", "#2F6BFF", "#5B3CF5", "#D53CD1"], "shape": "round", "hair": "curl", "hair_colors": ["#58DBFB", "#D53CD1"],
           "eyes": "round", "eye_color": "#0B0B1C", "cheeks": "#D53CD1", "halo": ["#5B3CF5", "#D53CD1"],
           "headphone_accents": ["#58DBFB", "#D53CD1"], "accessories": [], "accessory_color": "#D53CD1", "name": "Original"}
SHAPES = ["round", "tall", "wide", "blob", "square"]
HAIR = ["curl", "tuft", "antenna", "spikes", "bun", "none"]
EYES = ["round", "big", "sparkle", "sleepy", "dots"]
ACCESSORIES = ["glasses", "sunglasses", "bow", "cat_ears", "bunny_ears", "crown", "beanie", "flower", "scarf"]

PRESETS = {
    "Original": {},
    "Sunset": {"body": ["#FFB36B", "#FF6B6B", "#C2185B"], "halo": ["#FF6B6B", "#FFB36B"], "hair_colors": ["#FFE27A", "#FF6B6B"],
               "cheeks": "#FF4F81", "headphone_accents": ["#FFB36B", "#C2185B"]},
    "Mint": {"body": ["#B8F2E6", "#5ED6B4", "#1BA784"], "halo": ["#5ED6B4", "#B8F2E6"], "hair": "tuft", "hair_colors": ["#1BA784", "#B8F2E6"],
             "cheeks": "#FF9AA2", "eyes": "big", "headphone_accents": ["#5ED6B4", "#1BA784"]},
    "Kitty": {"body": ["#F8B4D9", "#C084FC", "#8B5CF6"], "accessories": ["cat_ears", "bow"], "accessory_color": "#FF5FA2", "hair": "none",
              "eyes": "sparkle", "cheeks": "#FF5FA2", "halo": ["#C084FC", "#F8B4D9"], "headphone_accents": ["#F8B4D9", "#8B5CF6"]},
    "Robot": {"body": ["#CBD5E1", "#64748B", "#334155"], "shape": "square", "hair": "antenna", "hair_colors": ["#94A3B8", "#22D3EE"],
              "eyes": "dots", "eye_color": "#22D3EE", "cheeks": None, "halo": ["#22D3EE", "#64748B"], "headphone_accents": ["#22D3EE", "#F97316"]},
    "Cozy": {"body": ["#FDE68A", "#F59E0B", "#B45309"], "shape": "blob", "accessories": ["beanie", "scarf"], "accessory_color": "#DC2626",
             "eyes": "sleepy", "cheeks": "#F87171", "halo": ["#F59E0B", "#FDE68A"], "headphone_accents": ["#FDE68A", "#DC2626"]},
    "Royal": {"body": ["#A78BFA", "#6D28D9", "#312E81"], "accessories": ["crown"], "accessory_color": "#F43F5E", "eyes": "sparkle",
              "halo": ["#FBBF24", "#6D28D9"], "headphone_accents": ["#FBBF24", "#A78BFA"]},
    "Cool": {"body": ["#38BDF8", "#1D4ED8", "#0F172A"], "accessories": ["sunglasses"], "accessory_color": "#E2E8F0", "hair": "spikes",
             "hair_colors": ["#0EA5E9", "#1E293B"], "cheeks": None, "halo": ["#38BDF8", "#1D4ED8"]},
}

HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _color(v, fallback):
    return v.upper() if isinstance(v, str) and HEX.fullmatch(v.strip()) else fallback


def _colors(v, fallback, lo=1, hi=4):
    if not isinstance(v, list):
        return fallback
    out = [c.upper() for c in v if isinstance(c, str) and HEX.fullmatch(c.strip())][:hi]
    return out if len(out) >= lo else fallback


def clean(spec: dict, base: dict | None = None) -> dict:
    """Merge a (partial) spec onto base and validate every field."""
    s = {**DEFAULT, **(base or {}), **{k: v for k, v in (spec or {}).items() if k in DEFAULT}}
    return {
        "body": _colors(s["body"], DEFAULT["body"]),
        "shape": s["shape"] if s["shape"] in SHAPES else "round",
        "hair": s["hair"] if s["hair"] in HAIR else "curl",
        "hair_colors": _colors(s["hair_colors"], DEFAULT["hair_colors"], hi=3),
        "eyes": s["eyes"] if s["eyes"] in EYES else "round",
        "eye_color": _color(s["eye_color"], DEFAULT["eye_color"]),
        "cheeks": None if s["cheeks"] in (None, "", "none") else _color(s["cheeks"], DEFAULT["cheeks"]),
        "halo": _colors(s["halo"], DEFAULT["halo"], hi=3),
        "headphone_accents": _colors(s["headphone_accents"], DEFAULT["headphone_accents"], lo=2, hi=2),
        "accessories": [a for a in dict.fromkeys(s["accessories"] or []) if a in ACCESSORIES][:3],
        "accessory_color": _color(s["accessory_color"], DEFAULT["accessory_color"]),
        "name": str(s.get("name") or "Custom")[:40],
    }


def preset(name: str) -> dict:
    return clean({**PRESETS[name], "name": name}, DEFAULT)

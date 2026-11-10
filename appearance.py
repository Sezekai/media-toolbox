"""The appearance system shared by the suite (DESIGN.md, "Appearance").

A theme is plain JSON (the *.theme.json format), so it can be saved, exported and imported between apps.
Presets and rules match lib/theme.js in Sezekai/waifu2x-batch, plus the Indigo background and the button style.
appearance.json in the data folder keeps the current look, the active theme's name and the saved themes."""
import json
import re
import shutil
from pathlib import Path

import fileops
import paths

THEME_VERSION = 1

BACKGROUNDS = {
    "obsidian": {"name": "Obsidian", "ground": "#0a0a0b", "rail": "#060607", "panel": "#111113", "raised": "#19191c", "raised2": "#232327", "field": "#070708", "line": "#212125", "line2": "#2e2e33", "text": "#ececee", "sec": "#a0a0a7", "faint": "#7d7d84", "stage": "#040405"},
    "carbon": {"name": "Carbon", "ground": "#0e0f10", "rail": "#0a0b0c", "panel": "#151618", "raised": "#1d1f22", "raised2": "#27292d", "field": "#0a0b0c", "line": "#25272b", "line2": "#33363b", "text": "#eaecee", "sec": "#9fa4aa", "faint": "#7d8188", "stage": "#070808"},
    "graphite": {"name": "Graphite", "ground": "#111214", "rail": "#0d0e10", "panel": "#18191c", "raised": "#202226", "raised2": "#2a2c31", "field": "#0d0e10", "line": "#2a2c31", "line2": "#383b42", "text": "#e8eaed", "sec": "#9aa0a8", "faint": "#80858d", "stage": "#0a0b0c"},
    "midnight": {"name": "Midnight", "ground": "#0c0e15", "rail": "#090b11", "panel": "#121521", "raised": "#1a1e2d", "raised2": "#252a3d", "field": "#0a0c12", "line": "#232839", "line2": "#30364b", "text": "#e8eaf2", "sec": "#9ba1b6", "faint": "#7b8095", "stage": "#07080d"},
    "ink": {"name": "Ink blue", "ground": "#08101f", "rail": "#060c18", "panel": "#0e1829", "raised": "#152237", "raised2": "#1d2d47", "field": "#060c17", "line": "#1b2840", "line2": "#273754", "text": "#e6edf8", "sec": "#94a3bd", "faint": "#76849b", "stage": "#040912"},
    "slate": {"name": "Slate", "ground": "#151a21", "rail": "#10141a", "panel": "#1b2129", "raised": "#232b35", "raised2": "#2d3641", "field": "#11161c", "line": "#2b333e", "line2": "#38424e", "text": "#e7ebf0", "sec": "#9ba5b2", "faint": "#818a95", "stage": "#0d1116"},
    "aubergine": {"name": "Aubergine", "ground": "#110d16", "rail": "#0c0910", "panel": "#18121f", "raised": "#21192b", "raised2": "#2c2239", "field": "#0c0910", "line": "#2a2135", "line2": "#3a2e48", "text": "#efe9f5", "sec": "#a99cb8", "faint": "#887c95", "stage": "#08060b"},
    "wine": {"name": "Wine", "ground": "#140b0e", "rail": "#0f0709", "panel": "#1c1014", "raised": "#26161c", "raised2": "#321e25", "field": "#0f0709", "line": "#2e1b21", "line2": "#3f262e", "text": "#f3e9eb", "sec": "#b39aa1", "faint": "#917c82", "stage": "#0a0507"},
    "forest": {"name": "Forest", "ground": "#0b110d", "rail": "#080c09", "panel": "#111912", "raised": "#18231a", "raised2": "#212e23", "field": "#080c09", "line": "#1d2a20", "line2": "#29392c", "text": "#e8f1ea", "sec": "#97ab9b", "faint": "#758678", "stage": "#050906"},
    "teal": {"name": "Deep teal", "ground": "#0a1214", "rail": "#070e10", "panel": "#101a1d", "raised": "#172427", "raised2": "#203033", "field": "#070e10", "line": "#1d2b2e", "line2": "#29393d", "text": "#e5f0ef", "sec": "#93aaa8", "faint": "#738887", "stage": "#050b0c"},
    "mocha": {"name": "Mocha", "ground": "#13110f", "rail": "#0e0c0b", "panel": "#1a1715", "raised": "#231f1c", "raised2": "#2e2925", "field": "#0e0c0b", "line": "#2b2622", "line2": "#3a332e", "text": "#efebe6", "sec": "#ada49b", "faint": "#898078", "stage": "#090807"},
    "indigo": {"name": "Indigo", "ground": "#0e0f17", "rail": "#0a0b12", "panel": "#161826", "raised": "#1d2032", "raised2": "#252942", "field": "#0b0c13", "line": "#2b3050", "line2": "#3a4170", "text": "#e8eaf6", "sec": "#8d93b5", "faint": "#7c82a8", "stage": "#07080d", "states": {"ok": "#5be38a", "warn": "#ffbf5a", "danger": "#ff5f73"}},
    "daylight": {"name": "Daylight", "ground": "#eef0f3", "rail": "#e4e7ec", "panel": "#f8f9fb", "raised": "#ffffff", "raised2": "#e8ebf0", "field": "#ffffff", "line": "#d9dde4", "line2": "#c7ccd5", "text": "#1b1e24", "sec": "#545b66", "faint": "#6b727c", "stage": "#dfe2e7"},
    "linen": {"name": "Linen", "ground": "#f2efe9", "rail": "#e9e4db", "panel": "#faf8f4", "raised": "#ffffff", "raised2": "#ece7de", "field": "#ffffff", "line": "#ddd6ca", "line2": "#cbc2b3", "text": "#25211b", "sec": "#5f574c", "faint": "#776f64", "stage": "#e4ded3"},
}

BG_LABELS = [("ground", "Ground"), ("rail", "Side rail"), ("panel", "Panels"), ("raised", "Buttons"),
             ("raised2", "Hover and selected"), ("field", "Fields and lists"), ("line", "Lines"),
             ("line2", "Strong lines"), ("text", "Text"), ("sec", "Secondary text"), ("faint", "Faint text"),
             ("stage", "Image area")]
STATE_LABELS = [("ok", "Success"), ("warn", "Warning"), ("danger", "Danger")]
DEFAULT_STATES = {"ok": "#52d39a", "warn": "#f2b64c", "danger": "#f0616d"}

ACCENTS = {
    "limeTeal": {"name": "Lime → Teal", "stops": ["#b6f05a", "#2fd6b4"]},
    "violetBlue": {"name": "Violet → Blue", "stops": ["#a497ff", "#74a0ff"]},
    "violetPink": {"name": "Violet → Pink", "stops": ["#b08cff", "#ff7ab6"]},
    "tealViolet": {"name": "Teal → Violet", "stops": ["#2fe0c0", "#9b86ff"]},
    "blueCyan": {"name": "Blue → Cyan", "stops": ["#6b98ff", "#3fd3f0"]},
    "aquaLime": {"name": "Aqua → Lime", "stops": ["#3fe0e0", "#b6f05a"]},
    "mintSky": {"name": "Mint → Sky", "stops": ["#7ef0b6", "#7cc4ff"]},
    "amberPink": {"name": "Amber → Pink", "stops": ["#ffb547", "#ff6f91"]},
    "coralOrange": {"name": "Coral → Orange", "stops": ["#ff7a6b", "#ffb04d"]},
    "sunset": {"name": "Sunset", "stops": ["#ffb347", "#ff6a88", "#b47cff"]},
    "rosePeach": {"name": "Rose → Peach", "stops": ["#ff8fb1", "#ffc59b"]},
    "goldLime": {"name": "Gold → Lime", "stops": ["#ffd25e", "#b6f05a"]},
    "aurora": {"name": "Aurora", "stops": ["#5ef0c0", "#5aa8ff", "#c08cff"]},
    "solidLime": {"name": "Lime", "stops": ["#b6f05a"]},
    "solidTeal": {"name": "Teal", "stops": ["#2fd6b4"]},
    "solidBlue": {"name": "Blue", "stops": ["#5aa6ff"]},
    "solidViolet": {"name": "Violet", "stops": ["#a497ff"]},
    "solidGreen": {"name": "Green", "stops": ["#4cc274"]},
    "solidOrange": {"name": "Orange", "stops": ["#ff9d4d"]},
    "solidPink": {"name": "Pink", "stops": ["#ff7ab6"]},
}

CORNERS = {
    "square": {"name": "Square", "control": 2, "panel": 3},
    "sharp": {"name": "Sharp", "control": 4, "panel": 6},
    "standard": {"name": "Standard", "control": 6, "panel": 10},
    "soft": {"name": "Soft", "control": 8, "panel": 14},
    "round": {"name": "Round", "control": 12, "panel": 18},
}
DENSITY = {
    "compact": {"name": "Compact", "control": 28, "row": 24},
    "comfortable": {"name": "Comfortable", "control": 32, "row": 28},
    "roomy": {"name": "Roomy", "control": 36, "row": 32},
}
TEXT_SIZES = [12, 13, 14, 15]
SYSTEM_FONTS = ["Segoe UI", "Segoe UI Variable Text", "Satoshi", "Bahnschrift", "Aptos", "Calibri"]


def _bg(key):
    b = dict(BACKGROUNDS[key])
    b.pop("name", None)
    b.pop("states", None)
    return b


DEFAULT_THEME = {
    "version": THEME_VERSION,
    "name": "Default",
    "background": _bg("obsidian"),
    "states": dict(DEFAULT_STATES),
    "accent": {"stops": list(ACCENTS["limeTeal"]["stops"]), "angle": 90, "onAccent": "auto"},
    "font": {"family": "Inter", "size": 13},
    "corners": {"control": 6, "panel": 10},
    "density": {"control": 28, "row": 24},
    "buttons": {"style": "flat"},
    "outline": {"colour": "", "width": 2},   # focus rings and the selected item's outline; "" = the accent
    "highlight": {"colour": ""},             # the tint behind selected, ticked and chosen things; "" = the accent
}

# Version 1's look, saved as a theme so it is one click away.
CLASSIC_THEME = {
    **DEFAULT_THEME,
    "name": "Media Toolbox classic",
    "background": _bg("graphite"),
    "accent": {"stops": ["#4a9eff"], "angle": 90, "onAccent": "light"},
    "font": {"family": "Satoshi", "size": 13},
    "corners": {"control": 5, "panel": 7},
}

HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _expand(h):
    return "#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h


def _color(v, default):
    return _expand(v.strip().lower()) if isinstance(v, str) and HEX.match(v.strip()) else default


def _clamp(v, lo, hi, default):
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, n))


def normalize(t):
    """Fill gaps from the default and drop anything invalid, so an imported or hand-edited theme can't break the app."""
    d = DEFAULT_THEME
    t = t if isinstance(t, dict) else {}

    def part(name):
        value = t.get(name)
        return value if isinstance(value, dict) else {}

    bg = {k: _color(part("background").get(k), d["background"][k]) for k, _ in BG_LABELS}
    st = {k: _color(part("states").get(k), d["states"][k]) for k, _ in STATE_LABELS}
    acc = part("accent")
    stops = [s for s in (_color(s, None) for s in acc.get("stops", []) if isinstance(acc.get("stops"), list)) if s][:4]
    on = acc.get("onAccent")
    font = part("font")
    family = font.get("family") if isinstance(font.get("family"), str) and font.get("family").strip() else d["font"]["family"]
    name = t.get("name") if isinstance(t.get("name"), str) and t.get("name").strip() else d["name"]
    style = part("buttons").get("style")
    return {
        "version": THEME_VERSION,
        "name": name.strip()[:60],
        "background": bg,
        "states": st,
        "accent": {"stops": stops or list(d["accent"]["stops"]), "angle": _clamp(acc.get("angle"), 0, 360, 90),
                   "onAccent": on if on in ("dark", "light") else "auto"},
        "font": {"family": family.strip()[:80], "size": _clamp(font.get("size"), 11, 16, 13)},
        "corners": {"control": _clamp(part("corners").get("control"), 0, 16, 6),
                    "panel": _clamp(part("corners").get("panel"), 0, 24, 10)},
        "density": {"control": _clamp(part("density").get("control"), 24, 44, 28),
                    "row": _clamp(part("density").get("row"), 20, 40, 24)},
        "buttons": {"style": style if style in ("flat", "glow") else "flat"},
        "outline": {"colour": _color(part("outline").get("colour"), "") or "",
                    "width": _clamp(part("outline").get("width"), 1, 4, 2)},
        "highlight": {"colour": _color(part("highlight").get("colour"), "") or ""},
    }


def luminance(hex_colour):
    h = _expand(hex_colour)
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    x, y = sorted([luminance(a), luminance(b)], reverse=True)
    return (x + 0.05) / (y + 0.05)


DARK_ON, LIGHT_ON = "#0b0c0f", "#ffffff"


def on_accent(theme):
    """The text colour that stays readable on every colour of the gradient (or the pinned one)."""
    mode = theme["accent"]["onAccent"]
    if mode == "dark":
        return DARK_ON
    if mode == "light":
        return LIGHT_ON

    def worst(c):
        return min(contrast(c, s) for s in theme["accent"]["stops"])

    return DARK_ON if worst(DARK_ON) >= worst(LIGHT_ON) else LIGHT_ON


def on_accent_contrast(theme):
    on = on_accent(theme)
    return min(contrast(on, s) for s in theme["accent"]["stops"])


def is_light(theme):
    return luminance(theme["background"]["ground"]) > 0.4


def with_background(theme, key):
    t = normalize(theme)
    t["background"] = _bg(key)
    t["states"] = dict(BACKGROUNDS[key].get("states", DEFAULT_STATES))
    return t


def describe(theme):
    """"Obsidian · Lime → Teal · Inter · Standard · Compact", naming the parts that match a preset."""
    t = normalize(theme)
    bg = next((k for k in BACKGROUNDS if all(BACKGROUNDS[k][f] == t["background"][f] for f, _ in BG_LABELS)), None)
    acc = next((k for k in ACCENTS if ACCENTS[k]["stops"] == t["accent"]["stops"]), None)
    cor = next((k for k in CORNERS if CORNERS[k]["control"] == t["corners"]["control"]
                and CORNERS[k]["panel"] == t["corners"]["panel"]), None)
    den = next((k for k in DENSITY if DENSITY[k]["control"] == t["density"]["control"]
                and DENSITY[k]["row"] == t["density"]["row"]), None)
    return {
        "background": bg, "accent": acc, "corners": cor, "density": den,
        "text": " · ".join([BACKGROUNDS[bg]["name"] if bg else "Custom background",
                                 ACCENTS[acc]["name"] if acc else "Custom accent", t["font"]["family"],
                                 CORNERS[cor]["name"] if cor else "Custom corners",
                                 DENSITY[den]["name"] if den else "Custom density"]),
    }


def same_look(a, b):
    a, b = normalize(a), normalize(b)
    a.pop("name"), b.pop("name")
    return a == b


# ----- the store: appearance.json -----
def _store_file():
    return paths.place("data") / "appearance.json"


def load_store():
    data = fileops.read_json(_store_file(), None)
    if not isinstance(data, dict):
        data = {"current": dict(DEFAULT_THEME), "active": "Default", "saved": [dict(CLASSIC_THEME)]}
    data["current"] = normalize(data.get("current"))
    data["saved"] = [normalize(t) for t in data.get("saved", []) if isinstance(t, dict)]
    data.setdefault("active", None)
    return data


def save_store(store):
    try:
        fileops.write_json(_store_file(), store)
    except OSError:
        pass


def read_theme_file(path):
    with open(path, encoding="utf-8") as f:
        return normalize(json.load(f))


def write_theme_file(theme, path):
    fileops.write_json(path, normalize(theme))


# ----- fonts -----
def bundled_fonts():
    """[{id, family, mono, files:[{weight, file}]}] from fonts/fonts.json beside the program."""
    index = fileops.read_json(paths.bundle_dir() / "fonts" / "fonts.json", [])
    return index if isinstance(index, list) else []


def added_fonts():
    index = fileops.read_json(paths.fonts_dir() / "index.json", [])
    return index if isinstance(index, list) else []


def register_fonts():
    """Make bundled and added fonts available to Qt. Returns the list of families that loaded."""
    from PySide6.QtGui import QFontDatabase
    loaded = []
    base = paths.bundle_dir() / "fonts"
    for entry in bundled_fonts():
        for f in entry.get("files", []):
            if QFontDatabase.addApplicationFont(str(base / f["file"])) >= 0 and entry["family"] not in loaded:
                loaded.append(entry["family"])
    for entry in added_fonts():
        for f in entry.get("files", []):
            QFontDatabase.addApplicationFont(str(paths.fonts_dir() / entry["id"] / f["file"]))
        loaded.append(entry["family"])
    return loaded


WEIGHT_WORDS = [("thin", 100), ("extralight", 200), ("ultralight", 200), ("light", 300), ("regular", 400),
                ("book", 400), ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800),
                ("ultrabold", 800), ("bold", 700), ("black", 900), ("heavy", 900)]


def guess_font(files):
    """(family name, [(file, weight, italic)]) guessed from file names like 'Satoshi-BoldItalic.otf'."""
    guessed, family = [], None
    for f in files:
        stem = Path(f).stem
        low = re.sub(r"[^a-z]", "", stem.lower())
        weight = next((w for word, w in sorted(WEIGHT_WORDS, key=lambda x: -len(x[0])) if word in low), 400)
        italic = "italic" in low or "oblique" in low
        guessed.append((f, weight, italic))
        base = re.split(r"[-_ ]", stem)[0]
        family = family or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    return family or "My font", guessed


def add_font(name, files):
    """Copy font files into the data folder and record them. Returns the new index entry."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "font"
    folder = paths.ensure(paths.fonts_dir() / slug)
    _family, guessed = guess_font(files)
    entry = {"id": slug, "family": name, "files": []}
    for f, weight, italic in guessed:
        target = fileops.unique_path(folder, Path(f).name)
        shutil.copy2(f, target)
        entry["files"].append({"file": target.name, "weight": weight, "style": "italic" if italic else "normal"})
    index = [e for e in added_fonts() if e.get("id") != slug] + [entry]
    fileops.write_json(paths.fonts_dir() / "index.json", index)
    return entry

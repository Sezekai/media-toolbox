"""Colours, fonts, sizes and widget builders. Values change when the user picks options in Appearance."""
import ctypes
import os
import sys
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

from themes import COLOUR_NAMES, DEFAULT_THEME, PALETTES

BUNDLED_FAMILY = "Inter"
FALLBACK_FAMILY = "Segoe UI"
MONO = "Consolas"

# Chosen in Appearance (and remembered between runs)
WANTED_FAMILY = BUNDLED_FAMILY
FAMILY = BUNDLED_FAMILY
TEXT_SCALE = 1.0
UI_SCALE = 1.0
RADIUS_SCALE = 1.0
CURRENT_THEME = DEFAULT_THEME


def use_theme(name):
    """Switch the colours to the named theme."""
    global CURRENT_THEME
    palette = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    CURRENT_THEME = name if name in PALETTES else DEFAULT_THEME
    for colour in COLOUR_NAMES:
        globals()[colour] = palette[colour]


def set_sizes(text_scale, ui_scale, radius_scale):
    global TEXT_SCALE, UI_SCALE, RADIUS_SCALE
    TEXT_SCALE, UI_SCALE, RADIUS_SCALE = float(text_scale), float(ui_scale), float(radius_scale)


def set_family(name):
    global WANTED_FAMILY
    WANTED_FAMILY = name or BUNDLED_FAMILY


def _bundle_path(*parts):
    """Path to a bundled file, both when running from source and inside the PyInstaller .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def load_fonts():
    """Make the bundled Inter font usable by this app on Windows, without installing it.
    Call once, before the main window is created."""
    if sys.platform != "win32":
        return
    FR_PRIVATE = 0x10  # visible only to this process
    for name in ("Inter-Regular.ttf", "Inter-Bold.ttf"):
        path = _bundle_path("fonts", name)
        if os.path.exists(path):
            ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0)


def installed_families(root):
    return set(tkfont.families(root))


def _resolve_family(root):
    global FAMILY
    available = installed_families(root)
    if WANTED_FAMILY in available:
        FAMILY = WANTED_FAMILY
    elif BUNDLED_FAMILY in available:
        FAMILY = BUNDLED_FAMILY
    else:
        FAMILY = FALLBACK_FAMILY


# ----- sizes -----
def px(n):
    """A size in pixels, scaled by the element size setting."""
    return max(1, round(n * UI_SCALE))


def radius(n):
    """A corner radius, scaled by the corner style setting."""
    return max(0, round(n * RADIUS_SCALE))


def _text_px(size):
    return max(8, round(size * TEXT_SCALE))  # 8 px floor keeps the small captions readable


def font(size=14, weight="normal"):
    return ctk.CTkFont(family=FAMILY, size=_text_px(size), weight=weight)


def tk_font(size=12, bold=False):
    """A font tuple for the plain Tk parts of the app (table headings and rows)."""
    return (FAMILY, _text_px(size), "bold" if bold else "normal")


def setup(root):
    """Apply the current theme and sizes. Call after creating the main window, and again after a change."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    _resolve_family(root)
    root.configure(fg_color=APP_BG)

    # Tables (ttk.Treeview) are not part of CustomTkinter, so they are styled here to match.
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    bordercolor=CARD_BORDER, lightcolor=CARD_BORDER, darkcolor=CARD_BORDER,
                    rowheight=px(36), font=tk_font(12))
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=HEADING, foreground=MUTED, bordercolor=CARD_BORDER,
                    relief="flat", font=tk_font(12, bold=True), padding=(10, 10))
    style.map("Treeview.Heading", background=[("active", SECONDARY_HOVER)])
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=SECONDARY, troughcolor=FIELD,
                        bordercolor=FIELD, arrowcolor=MUTED, lightcolor=SECONDARY, darkcolor=SECONDARY)
        style.map(f"{orient}.TScrollbar", background=[("active", SECONDARY_HOVER)])


def card(parent, **kw):
    """A rounded panel."""
    opts = {"fg_color": CARD, "corner_radius": radius(14), "border_width": 1, "border_color": CARD_BORDER}
    opts.update(kw)
    return ctk.CTkFrame(parent, **opts)


def _button_colours(kind):
    if kind == "primary":
        return GREEN, GREEN_HOVER, ON_GREEN
    if kind == "danger":
        return RED, RED_HOVER, "#ffffff"
    return SECONDARY, SECONDARY_HOVER, TEXT


def button(parent, text, command, kind="secondary", icon=None, width=None):
    fg, hover, text_colour = _button_colours(kind)
    opts = {"text": text, "command": command, "fg_color": fg, "hover_color": hover,
            "text_color": text_colour, "corner_radius": radius(10), "height": px(42),
            "font": font(14, "bold")}
    if icon is not None:
        opts.update(image=icon, compound="left")
    if width:
        opts["width"] = px(width)
    return ctk.CTkButton(parent, **opts)


def label(parent, text, size=14, weight="normal", color=None, **kw):
    return ctk.CTkLabel(parent, text=text, font=font(size, weight), text_color=color or TEXT, **kw)


def muted(parent, text, size=13, **kw):
    return label(parent, text, size, color=MUTED, **kw)


def entry(parent, var=None, width=None, **kw):
    opts = {"height": px(40), "corner_radius": radius(8), "fg_color": FIELD, "border_color": CARD_BORDER,
            "text_color": TEXT, "font": font(14)}
    if var is not None:
        opts["textvariable"] = var
    if width:
        opts["width"] = px(width)
    opts.update(kw)
    return ctk.CTkEntry(parent, **opts)


def switch(parent, text, var, command=None):
    """On/off switch bound to an IntVar (1 = on, 0 = off)."""
    opts = {"text": text, "variable": var, "onvalue": 1, "offvalue": 0, "font": font(14),
            "text_color": TEXT, "progress_color": GREEN, "fg_color": SECONDARY,
            "button_color": "#ffffff", "button_hover_color": "#e4e4ea", "height": px(28)}
    if command:
        opts["command"] = command
    return ctk.CTkSwitch(parent, **opts)


def combo(parent, values, variable, width=160, command=None):
    """A read-only dropdown in the current theme."""
    opts = {"values": values, "variable": variable, "state": "readonly", "width": px(width),
            "height": px(40), "corner_radius": radius(8), "font": font(14), "dropdown_font": font(14),
            "fg_color": FIELD, "border_color": CARD_BORDER, "text_color": TEXT,
            "button_color": SECONDARY, "button_hover_color": SECONDARY_HOVER,
            "dropdown_fg_color": CARD, "dropdown_hover_color": SECONDARY, "dropdown_text_color": TEXT}
    if command:
        opts["command"] = command
    return ctk.CTkComboBox(parent, **opts)


# Set the defaults once at import, so every name exists before the app starts.
use_theme(DEFAULT_THEME)

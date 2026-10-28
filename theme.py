"""Colours, fonts and widget builders for the dark interface."""
import ctypes
import os
import sys
from tkinter import ttk

import customtkinter as ctk

FAMILY = "Inter"            # falls back to Segoe UI if Inter can't be loaded
FALLBACK_FAMILY = "Segoe UI"
MONO = "Consolas"

APP_BG = "#0d0d0f"
SIDEBAR = "#121215"
CARD = "#1b1b20"
CARD_BORDER = "#2a2a31"
FIELD = "#101014"
TRACK = "#2a2a33"
NAV_HOVER = "#1f1f25"
NAV_ACTIVE = "#2b2b34"
TEXT = "#f5f5f7"
MUTED = "#a4a4ae"
GREEN = "#1f9d55"
GREEN_HOVER = "#27b865"
SECONDARY = "#2b2b33"
SECONDARY_HOVER = "#3a3a44"
RED = "#c0392b"
RED_HOVER = "#d94b3c"
SELECT = "#2e4a70"
HEADING = "#23232a"


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


def choose_family(root):
    """Use Inter if Tk can see it, otherwise fall back to Segoe UI."""
    global FAMILY
    import tkinter.font as tkfont
    if "Inter" not in tkfont.families(root):
        FAMILY = FALLBACK_FAMILY


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def setup(root):
    """Apply the dark theme. Call once, right after creating the main window."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root.configure(fg_color=APP_BG)
    choose_family(root)

    # Tables (ttk.Treeview) are not part of CustomTkinter, so they are styled here to match.
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    bordercolor=CARD_BORDER, lightcolor=CARD_BORDER, darkcolor=CARD_BORDER,
                    rowheight=32, font=(FAMILY, 11))
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=HEADING, foreground=MUTED, bordercolor=CARD_BORDER,
                    relief="flat", font=(FAMILY, 11, "bold"), padding=(8, 6))
    style.map("Treeview.Heading", background=[("active", SECONDARY_HOVER)])
    style.configure("Vertical.TScrollbar", background=SECONDARY, troughcolor=FIELD, bordercolor=FIELD,
                    arrowcolor=MUTED, lightcolor=SECONDARY, darkcolor=SECONDARY)
    style.map("Vertical.TScrollbar", background=[("active", SECONDARY_HOVER)])


def card(parent, **kw):
    """A rounded panel."""
    opts = {"fg_color": CARD, "corner_radius": 14, "border_width": 1, "border_color": CARD_BORDER}
    opts.update(kw)
    return ctk.CTkFrame(parent, **opts)


_BUTTON_COLOURS = {
    "primary": (GREEN, GREEN_HOVER),
    "secondary": (SECONDARY, SECONDARY_HOVER),
    "danger": (RED, RED_HOVER),
}


def button(parent, text, command, kind="secondary", icon=None, width=None):
    fg, hover = _BUTTON_COLOURS[kind]
    opts = {"text": text, "command": command, "fg_color": fg, "hover_color": hover,
            "text_color": "#ffffff", "corner_radius": 10, "height": 38, "font": font(13, "bold")}
    if icon is not None:
        opts.update(image=icon, compound="left")
    if width:
        opts["width"] = width
    return ctk.CTkButton(parent, **opts)


def label(parent, text, size=13, weight="normal", color=TEXT, **kw):
    return ctk.CTkLabel(parent, text=text, font=font(size, weight), text_color=color, **kw)


def muted(parent, text, size=12, **kw):
    return label(parent, text, size, color=MUTED, **kw)


def entry(parent, var=None, width=None, **kw):
    opts = {"height": 36, "corner_radius": 8, "fg_color": FIELD, "border_color": CARD_BORDER,
            "text_color": TEXT, "font": font(13)}
    if var is not None:
        opts["textvariable"] = var
    if width:
        opts["width"] = width
    opts.update(kw)
    return ctk.CTkEntry(parent, **opts)


def switch(parent, text, var):
    """On/off switch bound to an IntVar (1 = on, 0 = off)."""
    return ctk.CTkSwitch(parent, text=text, variable=var, onvalue=1, offvalue=0, font=font(13),
                         text_color=TEXT, progress_color=GREEN, fg_color=SECONDARY,
                         button_color="#ffffff", button_hover_color="#e4e4ea", height=24)

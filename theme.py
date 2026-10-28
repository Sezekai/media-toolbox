"""Dark theme with high-contrast text and coloured action buttons."""
from tkinter import ttk

BG = "#1b1d23"        # window background
PANEL = "#262a33"     # tabs, headings, raised areas
FIELD = "#101216"     # text boxes, list rows, log
TEXT = "#f5f7fa"      # main text (near white)
MUTED = "#c3c8d3"     # secondary text (still clearly readable)
BORDER = "#4a5063"
BTN = "#3b4152"
BTN_HOVER = "#4c5470"
ACCENT = "#4d8fe0"    # selection, focus, active tab
SELECT = "#2c5c99"
GREEN = "#2e9e5b"     # confirm / primary actions
GREEN_HOVER = "#3cb96e"
RED = "#c9453b"       # destructive actions
RED_HOVER = "#e05b50"
DISABLED = "#2a2e38"
DISABLED_TEXT = "#7d8494"

FONT = ("Segoe UI", 10)


def apply(root):
    """Set the dark colours for the whole app. Call once, before creating widgets."""
    root.configure(background=BG)
    # Dropdown lists of ttk.Combobox are plain Tk listboxes, so they need their own options.
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*Font", FONT)

    style = ttk.Style(root)
    style.theme_use("clam")  # the only built-in theme whose colours we can fully change
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Status.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10, "bold"))

    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))

    style.configure("TButton", background=BTN, foreground=TEXT, bordercolor=BORDER,
                    focuscolor=BTN, padding=(12, 6))
    style.map("TButton",
              background=[("active", BTN_HOVER), ("disabled", DISABLED)],
              foreground=[("disabled", DISABLED_TEXT)])

    style.configure("Go.TButton", background=GREEN, foreground="#ffffff", bordercolor=GREEN,
                    focuscolor=GREEN, padding=(12, 6), font=("Segoe UI", 10, "bold"))
    style.map("Go.TButton", background=[("active", GREEN_HOVER), ("disabled", DISABLED)])

    style.configure("Danger.TButton", background=RED, foreground="#ffffff", bordercolor=RED,
                    focuscolor=RED, padding=(12, 6))
    style.map("Danger.TButton", background=[("active", RED_HOVER), ("disabled", DISABLED)])

    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=4)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])

    style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, background=BTN,
                    arrowcolor=TEXT, bordercolor=BORDER, insertcolor=TEXT, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", FIELD)],
              selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", ACCENT)])

    style.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=FIELD,
                    indicatorforeground=TEXT, focuscolor=BG)
    style.map("TCheckbutton",
              background=[("active", BG)],
              indicatorbackground=[("selected", ACCENT), ("!selected", FIELD)])

    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 6, 2, 0))
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 7),
                    bordercolor=BORDER)
    style.map("TNotebook.Tab",
              background=[("selected", ACCENT), ("active", BTN_HOVER)],
              foreground=[("selected", "#ffffff"), ("active", TEXT)])

    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    bordercolor=BORDER, rowheight=26)
    style.map("Treeview",
              background=[("selected", SELECT)],
              foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=PANEL, foreground=TEXT, bordercolor=BORDER,
                    font=("Segoe UI", 10, "bold"), padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", BTN_HOVER)])

    style.configure("Vertical.TScrollbar", background=BTN, troughcolor=BG, bordercolor=BG,
                    arrowcolor=TEXT, lightcolor=BTN, darkcolor=BTN)
    style.map("Vertical.TScrollbar", background=[("active", BTN_HOVER)])

    style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor=FIELD,
                    bordercolor=BORDER, lightcolor=GREEN, darkcolor=GREEN, thickness=22)

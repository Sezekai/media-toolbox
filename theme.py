"""Turns the current look (appearance.py) into tokens and a Qt style sheet (DESIGN.md).

Every colour comes from a token. The accent is a gradient (qlineargradient); its last stop is used where only
one colour fits (icons, the selected outline). apply() restyles the running app in place, so the Look screen's
changes show straight away."""
import math
import os
import tempfile

from PySide6.QtGui import QColor, QFont, QPalette

import appearance

# ----- fixed sizes from DESIGN.md -----
GAP = 8           # between controls and between panels
PAD = 10          # inside panels
PAGE = 12         # around the page
LABEL_W = 88      # the shared label column in toolbars
ICON = 16         # icons in controls
RAIL_ICON = 19    # icons in the rail

# ----- tokens, set by use() -----
THEME = None
GROUND = RAIL = PANEL = RAISED = RAISED2 = FIELD = LINE = LINE2 = TEXT = SEC = FAINT = STAGE = "#000000"
OK = WARN = DANGER = "#000000"
STOPS = ["#b6f05a", "#2fd6b4"]
ANGLE = 90
ACCENT = ACC1 = ACC2 = "#2fd6b4"   # ACCENT is the last stop, for icons and outlines
ON_ACCENT = "#0b0c0f"
TINT_SELECT = TINT_TICK = TINT_PILL = TINT_HOVER = "#000000"
FAMILY, MONO = "Inter", "JetBrains Mono"
FONT_SIZE = 13
CONTROL_H, ROW_H = 28, 24
R_CONTROL, R_PANEL = 6, 10
GLOW = False
LIGHT = False
_listeners = []

# names used by older parts of the code
MUTED = SEC
CARD_BORDER = BORDER = LINE
GREEN = ACCENT
ON_GREEN = ON_ACCENT
SELECT = SELECT_SOFT = TRACK = RAISED_HOVER = "#000000"


def mix(a, b, t):
    """Colour a moved t of the way towards b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def use(theme):
    """Make a theme the current one (call apply(app) to restyle the window)."""
    global THEME, GROUND, RAIL, PANEL, RAISED, RAISED2, FIELD, LINE, LINE2, TEXT, SEC, FAINT, STAGE, OK, WARN, DANGER
    global STOPS, ANGLE, ACCENT, ACC1, ACC2, ON_ACCENT, TINT_SELECT, TINT_TICK, TINT_PILL, TINT_HOVER
    global FONT_SIZE, CONTROL_H, ROW_H, R_CONTROL, R_PANEL, GLOW, LIGHT
    global MUTED, CARD_BORDER, BORDER, GREEN, ON_GREEN, SELECT, SELECT_SOFT, TRACK, RAISED_HOVER
    t = appearance.normalize(theme)
    THEME = t
    bg = t["background"]
    GROUND, RAIL, PANEL, RAISED, RAISED2 = bg["ground"], bg["rail"], bg["panel"], bg["raised"], bg["raised2"]
    FIELD, LINE, LINE2, TEXT, SEC, FAINT, STAGE = (bg["field"], bg["line"], bg["line2"], bg["text"], bg["sec"],
                                                   bg["faint"], bg["stage"])
    OK, WARN, DANGER = t["states"]["ok"], t["states"]["warn"], t["states"]["danger"]
    STOPS, ANGLE = t["accent"]["stops"], t["accent"]["angle"]
    ACC1, ACC2 = STOPS[0], STOPS[-1]
    ACCENT = ACC2
    ON_ACCENT = appearance.on_accent(t)
    TINT_SELECT = mix(FIELD, ACCENT, 0.09)
    TINT_TICK = mix(FIELD, ACCENT, 0.13)
    TINT_PILL = mix(PANEL, ACCENT, 0.20)
    TINT_HOVER = mix(FIELD, TEXT, 0.04)
    FONT_SIZE = t["font"]["size"]
    CONTROL_H, ROW_H = t["density"]["control"], t["density"]["row"]
    R_CONTROL, R_PANEL = t["corners"]["control"], t["corners"]["panel"]
    GLOW = t["buttons"]["style"] == "glow"
    LIGHT = appearance.is_light(t)
    MUTED, CARD_BORDER, BORDER, GREEN, ON_GREEN = SEC, LINE, LINE, ACCENT, ON_ACCENT
    SELECT, SELECT_SOFT, TRACK, RAISED_HOVER = TINT_TICK, TINT_SELECT, RAISED2, RAISED2


use(appearance.DEFAULT_THEME)


def on_change(fn):
    """fn() runs after every restyle, e.g. to redraw icons in the new accent."""
    _listeners.append(fn)


def px(n):
    return max(0, round(n))


def radius(n):
    return max(0, round(n))


def text_px(role="body"):
    return {"caption": FONT_SIZE - 1, "body": FONT_SIZE, "heading": FONT_SIZE,
            "title": FONT_SIZE + 2}.get(role, FONT_SIZE)


WEIGHTS = {"body": 400, "caption": 400, "heading": 600, "title": 700, "button": 600}


def font(role="body", bold=False):
    f = QFont(FAMILY)
    f.setPixelSize(text_px(role))
    weight = 600 if bold and role in ("body", "caption") else WEIGHTS.get(role, 400)
    f.setWeight(QFont.Weight(weight))
    return f


def mono_font(size=None):
    f = QFont(MONO)
    f.setPixelSize(size or text_px("caption"))
    return f


def grad(stops=None, angle=None):
    """The accent as a QSS brush: a solid colour, or a qlineargradient drawn at the CSS angle."""
    stops = stops or STOPS
    angle = ANGLE if angle is None else angle
    if len(stops) == 1:
        return stops[0]
    a = math.radians(angle)
    sx, sy = math.sin(a), -math.cos(a)
    x1, y1, x2, y2 = 0.5 - sx / 2, 0.5 - sy / 2, 0.5 + sx / 2, 0.5 + sy / 2
    parts = ", ".join(f"stop:{i / (len(stops) - 1):.3f} {c}" for i, c in enumerate(stops))
    return f"qlineargradient(x1:{x1:.3f}, y1:{y1:.3f}, x2:{x2:.3f}, y2:{y2:.3f}, {parts})"


def qgradient(rect_w, rect_h, stops=None, angle=None):
    """The accent as a QLinearGradient for painting (progress bars drawn in code, the logo tile)."""
    from PySide6.QtGui import QLinearGradient
    stops = stops or STOPS
    angle = ANGLE if angle is None else angle
    a = math.radians(angle)
    sx, sy = math.sin(a), -math.cos(a)
    cx, cy = rect_w / 2, rect_h / 2
    half = (abs(sx) * rect_w + abs(sy) * rect_h) / 2
    g = QLinearGradient(cx - sx * half, cy - sy * half, cx + sx * half, cy + sy * half)
    for i, c in enumerate(stops):
        g.setColorAt(i / max(1, len(stops) - 1), QColor(c))
    return g


def _resolve_family():
    from PySide6.QtGui import QFontDatabase
    global FAMILY, MONO
    available = set(QFontDatabase.families())
    wanted = THEME["font"]["family"]
    FAMILY = wanted if wanted in available else "Inter"  # a missing font falls back to Inter
    MONO = "JetBrains Mono" if "JetBrains Mono" in available else "Consolas"


def _palette():
    p = QPalette()
    for role, colour in ((QPalette.Window, GROUND), (QPalette.WindowText, TEXT), (QPalette.Base, FIELD),
                         (QPalette.AlternateBase, PANEL), (QPalette.Text, TEXT), (QPalette.Button, RAISED),
                         (QPalette.ButtonText, TEXT), (QPalette.Highlight, TINT_TICK),
                         (QPalette.HighlightedText, TEXT), (QPalette.ToolTipBase, PANEL),
                         (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, FAINT), (QPalette.Link, ACCENT)):
        p.setColor(role, QColor(colour))
    if hasattr(QPalette, "Accent"):
        p.setColor(QPalette.Accent, QColor(ACCENT))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(FAINT))
    return p


def _png(name, draw):
    """A tiny generated image (chevrons, ticks, sort arrows) so the style sheet needs no bundled files."""
    path = os.path.join(tempfile.gettempdir(), f"mediatoolbox2_{name}.png")
    if not os.path.exists(path):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
        draw(ImageDraw.Draw(img))
        img.resize((14, 14), Image.LANCZOS).save(path)
    return path.replace("\\", "/")


def _chevron(colour):
    return _png("chev_" + colour.lstrip("#"),
                lambda d: d.line([(14, 21), (28, 35), (42, 21)], fill=colour, width=6, joint="curve"))


def _check(colour):
    return _png("check_" + colour.lstrip("#"),
                lambda d: d.line([(13, 29), (24, 40), (44, 16)], fill=colour, width=7, joint="curve"))


def _tri(colour, up):
    pts = [(14, 36), (42, 36), (28, 18)] if up else [(14, 20), (42, 20), (28, 38)]
    return _png(("up_" if up else "down_") + colour.lstrip("#"), lambda d: d.polygon(pts, fill=colour))


def _tag(name, colour, fill):
    fc = text_px("caption")
    return (f'QLabel[tag="{name}"] {{ background: {fill}; color: {colour}; border-radius: 10px; padding: 0px 8px; '
            f'font-size: {fc}px; font-weight: 600; min-height: 20px; max-height: 20px; }}')


def stylesheet():
    rh, rc, rp = ROW_H, R_CONTROL, R_PANEL
    inner = CONTROL_H - 2  # inside a one-pixel border
    g = grad()
    g_hover = grad([mix(s, "#ffffff", 0.12) for s in STOPS])
    fs, fc = text_px("body"), text_px("caption")
    tags = "\n".join([_tag("acc", TEXT, TINT_PILL), _tag("ok", OK, mix(PANEL, OK, 0.16)),
                      _tag("warn", WARN, mix(PANEL, WARN, 0.16)), _tag("danger", DANGER, mix(PANEL, DANGER, 0.16)),
                      _tag("plain", SEC, RAISED2)])
    return f"""
    * {{ outline: 0; }}
    QWidget {{ color: {TEXT}; font-family: "{FAMILY}"; font-size: {fs}px; }}
    QMainWindow, QWidget#root, QStackedWidget, QWidget#page, QWidget#pagehost {{ background: {GROUND}; }}
    QLabel {{ background: transparent; }}
    QLabel[role="title"] {{ font-size: {text_px('title')}px; font-weight: 700; }}
    QLabel[role="heading"] {{ font-weight: 600; }}
    QLabel[role="muted"] {{ color: {SEC}; }}
    QLabel[role="caption"] {{ color: {FAINT}; font-size: {fc}px; }}
    QLabel[role="empty"] {{ color: {FAINT}; }}
    QLabel[role="value"] {{ color: {TEXT}; }}
    QLabel[role="mono"] {{ font-family: "{MONO}"; font-size: {fc}px; color: {SEC}; }}
    QLabel[role="warn"] {{ color: {WARN}; }}
    QLabel[role="danger"] {{ color: {DANGER}; }}
    QLabel[role="ok"] {{ color: {OK}; }}
    QLabel[role="accent"] {{ color: {ACCENT}; }}
    {tags}

    QFrame#titlebar {{ background: {GROUND}; border-bottom: 1px solid {LINE}; }}
    QLabel#appname {{ font-size: 12px; font-weight: 600; color: {TEXT}; }}
    QLabel#screenname {{ font-size: 12px; color: {FAINT}; }}
    QPushButton#winbtn, QPushButton#winclose {{ background: {GROUND}; border: none; border-radius: 0px; padding: 0px;
        min-height: 31px; max-height: 31px; min-width: 46px; max-width: 46px; }}
    QPushButton#winbtn:hover {{ background: {RAISED2}; }}
    QPushButton#winclose:hover {{ background: #c42b1c; }}
    QPushButton#pill {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 11px; padding: 0px 10px;
        min-height: 20px; max-height: 20px; color: {SEC}; font-size: {fc}px; font-weight: 400; }}
    QPushButton#pill:hover {{ background: {TINT_PILL}; color: {TEXT}; }}

    QFrame#rail {{ background: {RAIL}; border-right: 1px solid {LINE}; }}
    QToolButton#railbtn {{ background: transparent; border: none; border-radius: {rc}px; color: {SEC};
        font-size: 11px; font-weight: 400; padding: 5px 0px 4px 0px; min-height: 0px; max-height: 1000px; }}
    QToolButton#railbtn:hover {{ background: {RAISED}; color: {TEXT}; }}
    QToolButton#railbtn[active="true"] {{ background: {RAISED}; color: {TEXT}; }}
    QToolButton#railbtn:focus {{ border: 2px solid {ACCENT}; padding: 3px 0px 2px 0px; }}

    QFrame#toolbar, QFrame#panel, QFrame#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: {rp}px; }}
    QFrame#tile {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: {rp}px; }}
    QFrame#tile[chosen="true"] {{ border: 1px solid {ACCENT}; }}
    QFrame#copy {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: {rp}px; }}
    QFrame#copy:hover {{ border: 1px solid {LINE2}; }}
    QFrame#copy[best="true"] {{ border: 1px solid {ACCENT}; }}
    QFrame#preview, QLabel#stage, QWidget#stage {{ background: {STAGE}; border: 1px solid {LINE};
        border-radius: {max(0, rc - 1)}px; }}
    QFrame#divider {{ background: {LINE}; border: none; }}
    QFrame#statusbar {{ background: {PANEL}; border-top: 1px solid {LINE}; }}
    QFrame#drawer {{ background: {PANEL}; border-top: 1px solid {LINE2}; }}
    QFrame#selbar {{ background: {mix(PANEL, ACCENT, 0.08)}; border: 1px solid {mix(PANEL, ACCENT, 0.26)};
        border-radius: {rc}px; }}
    QFrame#banner {{ background: {mix(PANEL, ACCENT, 0.06)}; border: 1px solid {mix(PANEL, ACCENT, 0.26)};
        border-radius: {rp}px; }}
    QWidget#scrim {{ background: rgba(0, 0, 0, 140); }}
    QFrame#dialog {{ background: {PANEL}; border: 1px solid {LINE2}; border-radius: 12px; }}
    QFrame#toast {{ background: {RAISED}; border: 1px solid {LINE2}; border-radius: {rp}px; }}
    QFrame#popup {{ background: {PANEL}; border: 1px solid {LINE2}; border-radius: {rp}px; }}

    QPushButton, QToolButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: {rc}px;
        padding: 0px 12px; min-height: {inner}px; max-height: {inner}px; font-weight: 600; }}
    QPushButton:hover, QToolButton:hover {{ background: {RAISED2}; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {ACCENT}; padding: 0px 11px; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {FAINT}; background: {PANEL}; }}
    QPushButton:checked {{ background: {RAISED2}; }}
    QPushButton[kind="primary"] {{ background: {g}; color: {ON_ACCENT}; border: 1px solid {ACC2}; }}
    QPushButton[kind="primary"]:hover {{ background: {g_hover}; }}
    QPushButton[kind="primary"]:focus {{ border: 2px solid {TEXT}; }}
    QPushButton[kind="primary"]:disabled {{ background: {RAISED}; color: {FAINT}; border: 1px solid {LINE}; }}
    QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {SEC}; }}
    QPushButton[kind="ghost"]:hover {{ background: {RAISED}; color: {TEXT}; }}
    QPushButton[kind="ghost"]:focus {{ border: 2px solid {ACCENT}; }}
    QPushButton[kind="danger-ghost"] {{ background: transparent; color: {DANGER}; border: 1px solid {mix(PANEL, DANGER, 0.45)}; }}
    QPushButton[kind="danger-ghost"]:hover {{ background: {mix(PANEL, DANGER, 0.12)}; }}
    QPushButton[kind="danger"] {{ background: {DANGER}; color: #ffffff; border: 1px solid {DANGER}; }}
    QPushButton[kind="danger"]:hover {{ background: {mix(DANGER, '#ffffff', 0.12)}; }}
    QPushButton[kind="danger"]:focus {{ border: 2px solid {TEXT}; }}
    QToolButton::menu-indicator {{ image: url("{_chevron(SEC)}"); subcontrol-position: right center; right: 8px;
        width: 12px; height: 12px; }}
    QToolButton[popupMode="2"] {{ padding-right: 26px; }}

    QFrame#seg {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: {rc}px; }}
    QPushButton#segbtn {{ background: transparent; border: none; border-radius: {max(0, rc - 2)}px; color: {SEC};
        padding: 0px 10px; min-height: {inner - 4}px; max-height: {inner - 4}px; font-weight: 400; }}
    QPushButton#segbtn:hover {{ color: {TEXT}; }}
    QPushButton#segbtn:checked {{ background: {RAISED2}; color: {TEXT}; }}
    QPushButton#segbtn:focus {{ border: 2px solid {ACCENT}; padding: 0px 8px; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {FIELD}; color: {TEXT}; border: 1px solid {LINE2};
        border-radius: {rc}px; padding: 0px 8px; min-height: {inner}px; max-height: {inner}px;
        selection-background-color: {TINT_TICK}; selection-color: {TEXT}; }}
    QComboBox {{ background: {RAISED}; padding-right: 26px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {ACCENT}; padding: 0px 7px; }}
    QComboBox:focus {{ padding-right: 25px; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {FAINT}; }}
    QLineEdit#mono {{ font-family: "{MONO}"; font-size: {fc}px; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{_chevron(SEC)}"); width: 14px; height: 14px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0px; border: none; }}
    QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE2};
        selection-background-color: {TINT_TICK}; padding: 4px; outline: 0; }}

    QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator, QTreeView::indicator, QListView::indicator, QTableView::indicator {{
        width: 14px; height: 14px; border-radius: 3px; border: 1px solid {LINE2}; background: {FIELD}; }}
    QCheckBox::indicator:hover {{ border: 1px solid {SEC}; }}
    QCheckBox:focus {{ color: {TEXT}; }}
    QCheckBox::indicator:focus {{ border: 2px solid {ACCENT}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked, QTableView::indicator:checked {{
        background: {g}; border: 1px solid {ACC2}; image: url("{_check(ON_ACCENT)}"); }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 1px solid {LINE2}; background: {FIELD}; }}
    QRadioButton::indicator:checked {{ background: {g}; border: 4px solid {FIELD}; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {FAINT}; }}

    QTreeView, QListView, QTableView {{ background: {FIELD}; color: {TEXT}; border: 1px solid {LINE};
        border-radius: {rc}px; selection-background-color: {TINT_SELECT}; selection-color: {TEXT};
        alternate-background-color: {FIELD}; gridline-color: {LINE}; }}
    QTreeView::item, QListView::item, QTableView::item {{ min-height: {rh}px; padding: 0px 4px; border: none; }}
    QTreeView::item:hover, QListView::item:hover, QTableView::item:hover {{ background: {TINT_HOVER}; }}
    QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
        background: {TINT_SELECT}; color: {TEXT}; border-top: 1px solid {ACCENT}; border-bottom: 1px solid {ACCENT}; }}
    QListView#grid::item, QListView#grid::item:selected, QListView#grid::item:hover {{ background: transparent; border: none; }}
    QTreeView::branch {{ background: transparent; }}
    QHeaderView {{ background: {PANEL}; border: none; }}
    QHeaderView::section {{ background: {PANEL}; color: {SEC}; border: none; border-bottom: 1px solid {LINE};
        border-right: 1px solid {LINE}; padding: 0px 8px; min-height: {rh}px; font-size: {fc}px; font-weight: 600; }}
    QHeaderView::section:last {{ border-right: none; }}
    QHeaderView::up-arrow {{ image: url("{_tri(ACCENT, True)}"); width: 10px; height: 10px; }}
    QHeaderView::down-arrow {{ image: url("{_tri(ACCENT, False)}"); width: 10px; height: 10px; }}
    QTableCornerButton::section {{ background: {PANEL}; border: none; }}

    QPlainTextEdit, QTextEdit {{ background: {FIELD}; color: {SEC}; border: 1px solid {LINE}; border-radius: {rc}px;
        padding: 6px; font-family: "{MONO}"; font-size: {fc}px; selection-background-color: {TINT_TICK}; }}

    QProgressBar {{ background: {RAISED2}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {g}; border-radius: 3px; }}
    QSlider::groove:horizontal {{ background: {RAISED2}; height: 4px; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {g}; height: 4px; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; height: 12px; margin: -4px 0px; border-radius: 6px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {RAISED2}; border-radius: 3px; min-width: 24px; min-height: 24px; }}
    QScrollBar::handle:hover {{ background: {LINE2}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {LINE}; }}
    QTabBar::tab {{ background: transparent; color: {SEC}; padding: 4px 12px; border: none;
        border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
    QTabWidget::pane {{ border: none; }}

    QMenu {{ background: {PANEL}; border: 1px solid {LINE2}; padding: 4px; }}
    QMenu::item {{ padding: 5px 16px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {TINT_TICK}; }}
    QMenu::item:disabled {{ color: {FAINT}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
    QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE2}; padding: 4px 6px; }}
    """


def apply(app):
    """Apply the current look to the whole application, in place."""
    from PySide6.QtWidgets import QPushButton
    _resolve_family()
    f = font("body")
    try:
        f.setFeature(QFont.Tag("tnum"), 1)  # even-width numbers wherever digits line up
    except Exception:
        pass
    app.setFont(f)
    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())
    for w in app.allWidgets():
        if isinstance(w, QPushButton) and w.property("kind") == "primary":
            set_glow(w)
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


def set_glow(button):
    """The Glow button style: a soft accent glow along the bottom of primary buttons (off by default)."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    if GLOW:
        effect = QGraphicsDropShadowEffect(button)
        effect.setColor(QColor(ACCENT))
        effect.setBlurRadius(16)
        effect.setOffset(0, 3)
        button.setGraphicsEffect(effect)
    elif button.graphicsEffect() is not None:
        button.setGraphicsEffect(None)

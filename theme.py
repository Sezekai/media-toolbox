"""Colours, fonts and sizes. One size setting scales the text and every element together."""
import os
import sys
import tempfile

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from themes import COLOUR_NAMES, DEFAULT_THEME, PALETTES

BUNDLED_FAMILY = "Inter"
FALLBACK_FAMILY = "Segoe UI"
MONO = "Consolas"

# Chosen in Appearance (and remembered between runs)
WANTED_FAMILY = BUNDLED_FAMILY
FAMILY = BUNDLED_FAMILY
SIZE = 1.0          # text and elements
RADIUS = 1.0        # corners
CURRENT_THEME = DEFAULT_THEME

# Every text size is one fixed base multiplied by SIZE, so the sizes always keep their proportions.
TEXT_BASE = {"caption": 12, "body": 14, "heading": 16, "title": 21, "sample": 20}
TEXT_FLOOR = 8      # px, the smallest text ever drawn


def use_theme(name):
    """Switch the colours to the named theme."""
    global CURRENT_THEME
    palette = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    CURRENT_THEME = name if name in PALETTES else DEFAULT_THEME
    for colour in COLOUR_NAMES:
        globals()[colour] = palette[colour]


def set_look(size, radius):
    global SIZE, RADIUS
    SIZE, RADIUS = float(size), float(radius)


def set_family(name):
    global WANTED_FAMILY
    WANTED_FAMILY = name or BUNDLED_FAMILY


def load_fonts():
    """Make the bundled Inter font available, without installing it. Call once, before the window is made."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("Inter-Regular.ttf", "Inter-Bold.ttf"):
        path = os.path.join(base, "fonts", name)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def installed_families():
    return set(QFontDatabase.families())


def resolve_family():
    global FAMILY
    available = installed_families()
    if WANTED_FAMILY in available:
        FAMILY = WANTED_FAMILY
    elif BUNDLED_FAMILY in available:
        FAMILY = BUNDLED_FAMILY
    else:
        FAMILY = FALLBACK_FAMILY


# ----- sizes -----
def px(n):
    """A size in pixels, scaled by the size setting."""
    return max(1, round(n * SIZE))


def radius(n):
    return max(0, round(n * RADIUS))


def text_px(role="body"):
    return max(TEXT_FLOOR, round(TEXT_BASE[role] * SIZE))


def font(role="body", bold=False):
    f = QFont(FAMILY)
    f.setPixelSize(text_px(role))
    f.setBold(bold)
    return f


def _palette():
    values = {name: QColor(globals()[name]) for name in COLOUR_NAMES}
    p = QPalette()
    p.setColor(QPalette.Window, values["APP_BG"])
    p.setColor(QPalette.WindowText, values["TEXT"])
    p.setColor(QPalette.Base, values["FIELD"])
    p.setColor(QPalette.AlternateBase, values["CARD"])
    p.setColor(QPalette.Text, values["TEXT"])
    p.setColor(QPalette.Button, values["SECONDARY"])
    p.setColor(QPalette.ButtonText, values["TEXT"])
    p.setColor(QPalette.Highlight, values["SELECT"])
    p.setColor(QPalette.HighlightedText, values["TEXT"])
    p.setColor(QPalette.ToolTipBase, values["CARD"])
    p.setColor(QPalette.ToolTipText, values["TEXT"])
    p.setColor(QPalette.PlaceholderText, values["MUTED"])
    return p


def _grip_file(vertical_bar, colour):
    """Three small dots, so a divider looks like something you can drag."""
    path = os.path.join(tempfile.gettempdir(), f"mediatoolbox_grip_{'v' if vertical_bar else 'h'}_{colour.lstrip('#')}.png")
    if not os.path.exists(path):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i in (-10, 0, 10):
            x, y = (20, 20 + i) if vertical_bar else (20 + i, 20)
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=colour)
        img.resize((12, 12), Image.LANCZOS).save(path)
    return path.replace("\\", "/")


def _chevron_file(colour):
    """A small down-pointing chevron, saved as a PNG so the style sheet can use it."""
    path = os.path.join(tempfile.gettempdir(), f"mediatoolbox_chevron_{colour.lstrip('#')}.png")
    if not os.path.exists(path):
        from PIL import Image, ImageDraw
        size = 40
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).line([(6, 14), (20, 28), (34, 14)], fill=colour, width=5, joint="curve")
        img.resize((12, 12), Image.LANCZOS).save(path)
    return path.replace("\\", "/")


def stylesheet():
    """The whole look of the app, built from the current colours and sizes."""
    g = globals()
    pad_v, pad_h = px(7), px(14)
    r_ctrl, r_field, r_card = radius(8), radius(7), radius(10)
    bar = px(12)
    return f"""
    QWidget {{ color: {g['TEXT']}; font-family: "{FAMILY}"; font-size: {text_px('body')}px; }}
    QWidget#root {{ background: {g['APP_BG']}; }}
    QWidget#page {{ background: transparent; }}
    QLabel {{ background: transparent; }}
    QLabel[role="title"] {{ font-size: {text_px('title')}px; font-weight: bold; }}
    QLabel[role="heading"] {{ font-size: {text_px('heading')}px; font-weight: bold; }}
    QLabel[role="muted"] {{ color: {g['MUTED']}; }}
    QLabel[role="caption"] {{ color: {g['MUTED']}; font-size: {text_px('caption')}px; }}
    QLabel[role="section"] {{ color: {g['MUTED']}; font-size: {text_px('caption')}px; font-weight: bold; }}
    QFrame#sidebar {{ background: {g['SIDEBAR']}; }}
    QFrame#rail {{ background: {g['SIDEBAR']}; border-right: 1px solid {g['CARD_BORDER']}; }}
    QFrame#toolbar {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: {r_card}px; }}
    QFrame#divider {{ background: {g['CARD_BORDER']}; border: none; }}
    QFrame#statusbar {{ background: {g['SIDEBAR']}; border-top: 1px solid {g['CARD_BORDER']}; }}
    QFrame#logpanel {{ background: {g['SIDEBAR']}; border-top: 1px solid {g['CARD_BORDER']}; }}
    QFrame#card {{ background: {g['CARD']}; border: 1px solid {g['CARD_BORDER']}; border-radius: {r_card}px; }}
    QFrame#preview {{ background: {g['FIELD']}; border-radius: {radius(10)}px; }}
    QPushButton {{ background: {g['SECONDARY']}; color: {g['TEXT']}; border: 1px solid transparent; border-radius: {r_ctrl}px;
                  padding: {pad_v}px {pad_h}px; min-height: {px(16)}px; font-weight: bold; }}
    QPushButton:focus {{ border: 1px solid {g['GREEN']}; }}
    QPushButton:hover {{ background: {g['SECONDARY_HOVER']}; }}
    QPushButton:disabled {{ color: {g['MUTED']}; }}
    QPushButton[kind="primary"] {{ background: {g['GREEN']}; color: {g['ON_GREEN']}; }}
    QPushButton[kind="primary"]:disabled {{ background: {g['SECONDARY']}; color: {g['MUTED']}; }}
    QPushButton[kind="primary"]:hover {{ background: {g['GREEN_HOVER']}; }}
    QPushButton[kind="danger"] {{ background: {g['RED']}; color: #ffffff; }}
    QPushButton[kind="danger"]:hover {{ background: {g['RED_HOVER']}; }}
    QPushButton[nav="true"] {{ background: transparent; color: {g['MUTED']}; text-align: left;
                              padding: {px(11)}px {px(14)}px; border-radius: {r_ctrl}px; }}
    QPushButton[nav="true"]:hover {{ background: {g['NAV_HOVER']}; }}
    QPushButton[rail="true"] {{ background: transparent; border: none; border-radius: {r_ctrl}px; padding: 0px; }}
    QPushButton[rail="true"]:hover {{ background: {g['NAV_HOVER']}; }}
    QPushButton[rail="true"][active="true"] {{ background: {g['NAV_ACTIVE']}; }}
    QPushButton:checked {{ background: {g['NAV_ACTIVE']}; }}
    QPushButton[nav="true"][active="true"] {{ background: {g['NAV_ACTIVE']}; color: {g['TEXT']}; font-weight: bold; }}
    QLineEdit, QComboBox, QSpinBox {{ background: {g['FIELD']}; color: {g['TEXT']}; border: 1px solid {g['CARD_BORDER']};
                           border-radius: {r_field}px; padding: {pad_v}px {pad_h}px; min-height: 1em;
                           selection-background-color: {g['SELECT']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {g['GREEN']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {g['MUTED']}; }}
    QComboBox {{ padding-right: {px(30)}px; }}
    QComboBox::drop-down {{ border: none; width: {px(30)}px; }}
    QComboBox::down-arrow {{ image: url("{_chevron_file(g['MUTED'])}"); width: {px(10)}px; height: {px(6)}px; }}
    QComboBox QAbstractItemView {{ background: {g['CARD']}; color: {g['TEXT']}; border: 1px solid {g['CARD_BORDER']};
                                  selection-background-color: {g['SECONDARY']}; outline: 0; padding: 4px; }}
    QCheckBox {{ spacing: {px(10)}px; background: transparent; }}
    QCheckBox::indicator {{ width: {px(18)}px; height: {px(18)}px; border-radius: {px(5)}px;
                           border: 2px solid {g['MUTED']}; background: {g['SECONDARY']}; }}
    QCheckBox::indicator:checked {{ background: {g['GREEN']}; border: 2px solid {g['GREEN']}; }}
    QTreeWidget {{ background: {g['FIELD']}; color: {g['TEXT']}; border: 1px solid {g['CARD_BORDER']};
                  border-radius: {r_field}px; selection-background-color: {g['SELECT']};
                  selection-color: {g['TEXT']}; outline: 0; }}
    QTreeWidget::item {{ padding: {px(5)}px 0px; }}
    QTreeWidget::indicator {{ width: {px(16)}px; height: {px(16)}px; border-radius: {px(4)}px;
                             border: 2px solid {g['MUTED']}; background: {g['SECONDARY']}; }}
    QTreeWidget::indicator:checked {{ background: {g['GREEN']}; border: 2px solid {g['GREEN']}; }}
    QHeaderView::section {{ background: {g['HEADING']}; color: {g['MUTED']}; border: none;
                           border-bottom: 1px solid {g['CARD_BORDER']};
                           border-right: 2px solid {g['SECONDARY']}; padding: {px(8)}px {px(10)}px;
                           font-weight: bold; }}
    QPlainTextEdit#log {{ background: {g['FIELD']}; color: {g['TEXT']}; border: 1px solid {g['CARD_BORDER']};
                         border-radius: {r_field}px; padding: {px(8)}px; font-family: "{MONO}";
                         font-size: {text_px('caption')}px; }}
    QProgressBar {{ background: {g['TRACK']}; border: none; border-radius: {px(6)}px; max-height: {px(12)}px;
                   min-height: {px(12)}px; }}
    QProgressBar::chunk {{ background: {g['GREEN']}; border-radius: {px(6)}px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: {bar}px; margin: 0px; }}
    QScrollBar:horizontal {{ background: transparent; height: {bar}px; margin: 0px; }}
    QScrollBar::handle {{ background: {g['SECONDARY']}; border-radius: {bar // 2}px; min-width: {px(30)}px;
                         min-height: {px(30)}px; }}
    QScrollBar::handle:hover {{ background: {g['SECONDARY_HOVER']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle:horizontal {{ background-color: {g['SECONDARY']}; background-repeat: no-repeat;
                                   background-position: center;
                                   background-image: url("{_grip_file(True, g['MUTED'])}"); }}
    QSplitter::handle:vertical {{ background-color: {g['SECONDARY']}; background-repeat: no-repeat;
                                 background-position: center;
                                 background-image: url("{_grip_file(False, g['MUTED'])}"); }}
    QSplitter::handle:hover {{ background-color: {g['GREEN']}; }}
    QToolTip {{ background: {g['CARD']}; color: {g['TEXT']}; border: 1px solid {g['CARD_BORDER']}; }}
    """


def apply(app):
    """Apply the current fonts, colours and sizes to the whole application."""
    resolve_family()
    app.setFont(font("body"))
    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())


use_theme(DEFAULT_THEME)

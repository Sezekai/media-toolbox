"""The look of the app: a compact dark theme with one accent colour the user can choose.

Every size comes from the small scale below, so controls, rows and gaps line up on every page."""
import os
import sys
import tempfile

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

# ----- colours -----
BG = "#111214"          # window ground
PANEL = "#18191c"       # tool bars, lists' panels, rail, status bar
RAISED = "#202226"      # buttons, headers
RAISED_HOVER = "#2a2c31"
FIELD = "#0d0e10"       # text boxes, lists
BORDER = "#2a2c31"      # one-pixel hairlines
TEXT = "#e8eaed"
MUTED = "#9aa0a8"       # secondary text, about 6.7:1 on PANEL
FAINT = "#6c727b"       # placeholders and disabled text
ACCENT = "#4a9eff"      # set by set_accent(); the colours below follow it
ACCENT_HOVER = "#6fb1ff"
ON_ACCENT = "#ffffff"   # text and icons on accent buttons
DANGER = "#e5484d"
DANGER_HOVER = "#f06569"
SELECT = "#1d3557"      # selected rows (the accent, darkened)
SELECT_SOFT = "#182436" # the active tool in the sidebar
TRACK = "#26282d"       # progress and slider tracks

# Older names used around the app
GREEN, ON_GREEN, CARD_BORDER = ACCENT, ON_ACCENT, BORDER

DEFAULT_ACCENT = "#4a9eff"
ACCENT_PRESETS = [  # (name, colour) offered in the accent menu; any other colour can be picked too
    ("Blue", "#4a9eff"), ("Sky", "#38b6e8"), ("Teal", "#22b3a3"), ("Green", "#3fb950"),
    ("Lime", "#8cc63f"), ("Amber", "#e0a526"), ("Orange", "#f07a2a"), ("Red", "#e5534b"),
    ("Pink", "#e5539e"), ("Purple", "#9b6cf0"), ("Indigo", "#6872f0"), ("Slate", "#8b98a9"),
]


def _mix(a, b, t):
    """Colour a moved t of the way towards colour b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def set_accent(colour):
    """Use a new accent colour everywhere. Call apply(app) afterwards to restyle the open window."""
    global ACCENT, ACCENT_HOVER, SELECT, SELECT_SOFT, GREEN
    c = QColor(colour)
    if not c.isValid():
        c = QColor(DEFAULT_ACCENT)
    ACCENT = c.name()
    ACCENT_HOVER = _mix(ACCENT, "#ffffff", 0.18)
    SELECT = _mix(ACCENT, PANEL, 0.68)
    SELECT_SOFT = _mix(ACCENT, PANEL, 0.82)
    GREEN = ACCENT

# ----- type -----
FAMILIES = ("Ubuntu", "Segoe UI", "Inter")  # Ubuntu (installed on the owner's PC), then fallbacks
FAMILY = "Ubuntu"
MONO = "Ubuntu Mono"
TEXT_SIZES = {"caption": 12, "body": 13, "heading": 13, "title": 15}

# ----- sizes (pixels) -----
CONTROL_H = 28   # every button, text box, drop-down and spin box
ROW_H = 24       # list rows
GAP = 8          # between controls
PAD = 10         # inside panels
R_CONTROL = 5
R_PANEL = 7


def px(n):
    """Kept for the pages: sizes are fixed, so this is the number itself."""
    return max(0, round(n))


def radius(n):
    return max(0, round(n))


def text_px(role="body"):
    return TEXT_SIZES.get(role, TEXT_SIZES["body"])


def font(role="body", bold=False):
    f = QFont(FAMILY)
    f.setPixelSize(text_px(role))
    f.setBold(bold or role in ("heading", "title"))
    return f


def load_fonts():
    """Make the bundled fallback face available (used only where Ubuntu and Segoe UI are missing)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("Inter-Regular.ttf", "Inter-Bold.ttf"):
        path = os.path.join(base, "fonts", name)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def _resolve_family():
    global FAMILY, MONO
    available = set(QFontDatabase.families())
    FAMILY = next((f for f in FAMILIES if f in available), "Segoe UI")
    MONO = next((f for f in ("Ubuntu Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono") if f in available),
                "Consolas")


def _palette():
    p = QPalette()
    for role, colour in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, FIELD),
                         (QPalette.AlternateBase, PANEL), (QPalette.Text, TEXT), (QPalette.Button, RAISED),
                         (QPalette.ButtonText, TEXT), (QPalette.Highlight, SELECT),
                         (QPalette.HighlightedText, TEXT), (QPalette.ToolTipBase, RAISED),
                         (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, FAINT),
                         (QPalette.Link, ACCENT)):
        p.setColor(role, QColor(colour))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(FAINT))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FAINT))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(FAINT))
    return p


def _png(name, draw):
    """A tiny generated image (chevron, check mark), so the style sheet can use it without bundled files."""
    path = os.path.join(tempfile.gettempdir(), f"mediatoolbox3_{name}.png")
    if not os.path.exists(path):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        draw(ImageDraw.Draw(img))
        img.resize((12, 12), Image.LANCZOS).save(path)
    return path.replace("\\", "/")


def _chevron():
    return _png("chevron_" + MUTED.lstrip("#"),
                lambda d: d.line([(10, 18), (24, 32), (38, 18)], fill=MUTED, width=6, joint="curve"))


def _check():
    return _png("check_" + ON_ACCENT.lstrip("#"),
                lambda d: d.line([(10, 25), (20, 35), (38, 13)], fill=ON_ACCENT, width=7, joint="curve"))


def stylesheet():
    ctrl = CONTROL_H - 2  # inside the one-pixel border
    return f"""
    * {{ outline: 0; }}
    QWidget {{ color: {TEXT}; font-family: "{FAMILY}"; font-size: {text_px('body')}px; }}
    QWidget#root, QStackedWidget, QWidget#page {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QLabel[role="title"] {{ font-size: {text_px('title')}px; font-weight: 600; }}
    QLabel[role="heading"] {{ font-weight: 600; }}
    QLabel[role="muted"] {{ color: {MUTED}; }}
    QLabel[role="caption"] {{ color: {MUTED}; font-size: {text_px('caption')}px; }}
    QLabel[role="empty"] {{ color: {FAINT}; }}
    QLabel[role="badge"] {{ color: {ACCENT}; font-size: {text_px('caption')}px; font-weight: 600; }}

    QFrame#rail {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
    QFrame#toolbar, QFrame#panel, QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER};
                                              border-radius: {R_PANEL}px; }}
    QFrame#copy {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: {R_PANEL}px; }}
    QFrame#copy:hover {{ border: 1px solid {FAINT}; }}
    QFrame#preview {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: {R_PANEL}px; }}
    QFrame#divider {{ background: {BORDER}; border: none; }}
    QFrame#statusbar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
    QFrame#logpanel {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}

    QPushButton, QToolButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER};
                   border-radius: {R_CONTROL}px; padding: 0px 12px; min-height: {ctrl}px; max-height: {ctrl}px; }}
    QPushButton:hover, QToolButton:hover {{ background: {RAISED_HOVER}; }}
    QPushButton:focus, QToolButton:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {FAINT}; background: {PANEL}; }}
    QPushButton:checked {{ background: {SELECT}; border: 1px solid {SELECT}; }}
    QPushButton[kind="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT};
                                   font-weight: normal; }}
    QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; border: 1px solid {ACCENT_HOVER}; }}
    QPushButton[kind="primary"]:disabled {{ background: {RAISED}; color: {FAINT}; border: 1px solid {BORDER}; }}
    QPushButton[kind="danger"] {{ color: {DANGER}; }}
    QPushButton[kind="danger"]:hover {{ background: {DANGER}; color: #ffffff; border: 1px solid {DANGER}; }}
    QPushButton[kind="danger"]:disabled {{ color: {FAINT}; }}
    QToolButton::menu-indicator {{ image: url("{_chevron()}"); subcontrol-position: right center;
                                  right: 8px; width: 10px; height: 10px; }}
    QToolButton[popupMode="2"] {{ padding-right: 24px; }}

    QPushButton[rail="true"] {{ background: transparent; border: none; border-radius: {R_CONTROL + 1}px;
                               color: {MUTED}; text-align: left; padding: 0px 0px 0px 7px;
                               min-height: 32px; max-height: 32px; }}
    QPushButton[rail="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
    QPushButton[rail="true"][active="true"] {{ background: {SELECT_SOFT}; color: {TEXT}; }}
    QLabel#brand {{ font-weight: 600; }}

    QLineEdit, QComboBox, QSpinBox {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER};
                   border-radius: {R_CONTROL}px; padding: 0px 8px; min-height: {ctrl}px; max-height: {ctrl}px;
                   selection-background-color: {SELECT}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {FAINT}; }}
    QComboBox {{ padding-right: 24px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{_chevron()}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER};
                                  selection-background-color: {SELECT}; padding: 4px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}

    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator, QTreeWidget::indicator, QListWidget::indicator {{
        width: 14px; height: 14px; border-radius: 3px; border: 1px solid {FAINT}; background: {FIELD}; }}
    QCheckBox::indicator:hover {{ border: 1px solid {MUTED}; }}
    QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT};
                                   image: url("{_check()}"); }}
    QCheckBox:disabled {{ color: {FAINT}; }}

    QTreeWidget, QListWidget {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER};
                   border-radius: {R_CONTROL}px; selection-background-color: {SELECT}; selection-color: {TEXT};
                   alternate-background-color: #121316; }}
    QTreeWidget::item, QListWidget::item {{ min-height: {ROW_H}px; padding: 0px 4px; border: none; }}
    QTreeWidget::item:hover, QListWidget::item:hover {{ background: #16181b; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
    QHeaderView {{ background: {FIELD}; border: none; }}
    QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                           border-right: 1px solid {BORDER}; padding: 0px 8px; min-height: {ROW_H}px;
                           font-size: {text_px('caption')}px; font-weight: 600; }}
    QHeaderView::section:last {{ border-right: none; }}
    QHeaderView::down-arrow, QHeaderView::up-arrow {{ width: 0px; height: 0px; }}

    QPlainTextEdit#log {{ background: {FIELD}; color: {MUTED}; border: 1px solid {BORDER};
                         border-radius: {R_CONTROL}px; padding: 6px; font-family: "{MONO}";
                         font-size: {text_px('caption')}px; selection-background-color: {SELECT}; }}

    QProgressBar {{ background: {TRACK}; border: none; border-radius: 2px; min-height: 4px; max-height: 4px; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::groove:horizontal {{ background: {TRACK}; height: 4px; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; height: 4px; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; height: 12px; margin: -4px 0px;
                                 border-radius: 6px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {RAISED_HOVER}; border-radius: 3px; min-width: 24px; min-height: 24px; }}
    QScrollBar::handle:hover {{ background: {FAINT}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {BORDER}; }}

    QMenu {{ background: {RAISED}; border: 1px solid {BORDER}; padding: 4px; }}
    QMenu::item {{ padding: 5px 16px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {SELECT}; }}
    QMenu::item:disabled {{ color: {FAINT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
    QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
    QMessageBox QLabel {{ color: {TEXT}; }}
    """


def apply(app):
    """Apply the font, colours and sizes to the whole application."""
    _resolve_family()
    app.setFont(font("body"))
    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())

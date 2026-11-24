"""The keyboard shortcuts popup (DESIGN.md, "Keyboard shortcuts popup").

K (or Keys in the rail) opens it over whatever screen is showing; K again, Esc or a click outside closes it.
It always fits inside the window: keys flow into more columns before anything scrolls, and a group's
heading stays with its first key. Resizing the window reflows it."""
from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

import icons
import theme
from widgets import button, label

KEYS = [
    ("Anywhere", [("K", "Open or close this list"), ("S", "Settings"), ("L", "Open or close the log"),
                  ("M", "Hide or show the side rail"), ("H", "Hide toolbars and side panels, to see only the work"),
                  ("F or F11", "Full screen"), ("/ or Ctrl+F", "Go to the search or filter box"),
                  ("Esc", "Close or leave, innermost first: this list, Gallery, full screen, the log, hidden panels"),
                  ("Ctrl+Z", "Undo the last move"), ("Ctrl+Shift+I", "Copy a debug report for bug reports")]),
    ("Lists, grids and Gallery", [("Ctrl+A", "Tick everything shown (again to untick)"),
                                  ("Space", "Tick or untick the selected item"),
                                  ("Ctrl+click", "Tick or untick an item"), ("Shift+click", "Tick a range"),
                                  ("Enter", "Open the selected item in Gallery"),
                                  ("Double-click", "Open in Gallery"),
                                  ("T", "Between Gallery and the list or grid you came from"),
                                  ("Mouse back button", "Gallery: back to the list or grid"),
                                  ("Click the video", "Gallery: play or pause"),
                                  ("← →  PgUp PgDn", "Previous or next item"),
                                  ("Home / End", "First or last item"),
                                  ("+ / −", "Bigger or smaller pictures and cards"),
                                  ("Ctrl+wheel", "The same, with the mouse"),
                                  ("0 / 1", "Gallery: fit to the window, or actual size")]),
    ("Dialogs", [("Enter", "The highlighted button"), ("Esc", "Cancel")]),
]

COL_W = 360      # one column
KEY_W = 140      # the keycap column inside it
GAP_X = 28       # between columns
MARGIN = 28      # between the popup and the window's edge
PAD = 20         # inside the popup


class KeysPopup(QWidget):
    def __init__(self, host, extra=None):
        """host: the window's root widget. extra(): this screen's own keys, as (title, [(key, does)]), or None."""
        super().__init__(host)
        self.host = host
        self.extra = extra
        self.setObjectName("scrim")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()
        host.installEventFilter(self)
        self.card = QFrame(self)
        self.card.setObjectName("dialog")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(PAD, PAD - 4, PAD - 8, PAD - 6)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(10)
        title = label("Keyboard shortcuts", "heading")
        title.setStyleSheet(f"font-size: {theme.text_px('title')}px;")
        head.addWidget(title)
        head.addWidget(label("K or Esc closes", "caption"))
        head.addStretch(1)
        close = button("", "ghost", icon=icons.icon("x", theme.SEC, 16), tip="Close (K or Esc)")
        close.clicked.connect(self.close_popup)
        head.addWidget(close)
        v.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(False)
        self.body = QWidget()
        self.body.setObjectName("keysbody")
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)
        self.blocks = []

    # ----- opening and closing -----
    def toggle(self):
        self.close_popup() if self.isVisible() else self.open_popup()

    def open_popup(self):
        self._build()
        self.setGeometry(self.host.rect())
        self.show()
        self.raise_()
        self._place()
        self.setFocus()

    def close_popup(self):
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self.host.rect())
            self._place()  # reflow the columns
        return False

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_popup()  # a click outside closes it
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_K):
            self.close_popup()
        event.accept()

    # ----- contents -----
    def _build(self):
        for b in self.blocks:
            b[0].deleteLater()
        self.blocks = []
        groups = list(KEYS)
        own = self.extra() if self.extra else None
        if own:
            groups.append(own)
        for title, rows in groups:
            head = label(title, "heading")
            head.setParent(self.body)
            self.blocks.append((head, True))
            for n, (key, does) in enumerate(rows):
                row = QFrame(self.body)
                row.setObjectName("keyrow")
                row.setProperty("alt", "true" if n % 2 == 0 else "false")  # every other row shaded
                h = QHBoxLayout(row)
                h.setContentsMargins(8, 4, 8, 4)
                h.setSpacing(10)
                cap_box = QWidget()
                cap_box.setFixedWidth(KEY_W)
                cb = QHBoxLayout(cap_box)
                cb.setContentsMargins(0, 0, 0, 0)
                cap = QLabel(key)
                cap.setObjectName("keycap")
                cb.addWidget(cap, 0, Qt.AlignLeft | Qt.AlignTop)
                cb.addStretch(1)
                h.addWidget(cap_box, 0, Qt.AlignTop)
                h.addWidget(label(does, "value", wrap=True), 1)
                self.blocks.append((row, False))
        for w, _head in self.blocks:
            w.ensurePolished()
            w.show()

    def _height(self, w):
        return w.heightForWidth(COL_W) if w.hasHeightForWidth() else w.sizeHint().height()

    def _columns(self, limit):
        """Fill columns top to bottom, each at most limit tall. A heading never ends a column."""
        cols, cur, used = [], [], 0
        spacing_row, spacing_head = 0, 14
        items = self.blocks
        for i, (w, is_head) in enumerate(items):
            h = self._height(w)
            need = h
            if is_head:
                nxt = items[i + 1] if i + 1 < len(items) else None
                need += (self._height(nxt[0]) + 4) if nxt else 0
                gap = spacing_head if cur else 0
            else:
                gap = 4 if cur and cur[-1][1] else (spacing_row if cur else 0)
            if cur and used + gap + need > limit:
                cols.append(cur)
                cur, used, gap = [], 0, 0
            cur.append((w, is_head, gap, h))
            used += gap + h
        if cur:
            cols.append(cur)
        return cols

    def _place(self):
        area = self.host.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        chrome = PAD + PAD + 12 + 34  # the popup's padding and title row
        room_h = max(120, area.height() - chrome)
        max_cols = max(1, (area.width() - 2 * PAD + GAP_X) // (COL_W + GAP_X))
        cols = self._columns(room_h)
        if len(cols) > max_cols:
            # Too narrow for enough columns: use them all, balanced, and let the popup scroll up and down.
            low, high = room_h, sum(self._height(w) + 14 for w, _h in self.blocks)
            while low < high:
                mid = (low + high) // 2
                if len(self._columns(mid)) <= max_cols:
                    high = mid
                else:
                    low = mid + 1
            cols = self._columns(low)
        heights = []
        for c, col in enumerate(cols):
            y = 0
            x = c * (COL_W + GAP_X)
            for w, _is_head, gap, h in col:
                y += gap
                w.setGeometry(QRect(x, y, COL_W, h))
                y += h
            heights.append(y)
        body_w = len(cols) * COL_W + (len(cols) - 1) * GAP_X
        body_h = max(heights) if heights else 0
        self.body.setFixedSize(body_w, body_h)
        scrolls = body_h > room_h
        bar = 12 if scrolls else 0
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if scrolls else Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedSize(body_w + bar, min(body_h, room_h))
        card_w = body_w + bar + PAD + PAD - 8
        card_h = min(body_h, room_h) + chrome
        self.card.setGeometry(QRect(area.x() + (area.width() - card_w) // 2,
                                    area.y() + (area.height() - card_h) // 2, card_w, card_h))

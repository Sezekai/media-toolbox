"""In-app dialogs and toasts (DESIGN.md: "Dialogs", "Toasts"). No Windows pop-ups: every question is drawn
inside the window over a dim scrim. Enter confirms; Esc cancels. File and folder pickers stay native."""
from pathlib import Path

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtGui import QColor

import icons
import theme
from widgets import ElidedLabel, TintDelegate, button, caption, label

_host = None  # the main window's root widget


def set_host(widget):
    global _host
    _host = widget


def host():
    return _host


class _Overlay(QWidget):
    """A scrim over the whole window with a dialog card in the middle."""

    def __init__(self, parent, width):
        super().__init__(parent)
        self.setObjectName("scrim")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        self.card = QFrame()
        self.card.setObjectName("dialog")
        self.card.setFixedWidth(width)
        shadow = QGraphicsDropShadowEffect(self.card)  # dialogs float, so they may cast a shadow
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        self.v = QVBoxLayout(self.card)
        self.v.setContentsMargins(20, 18, 20, 16)
        self.v.setSpacing(10)
        self.loop = QEventLoop()
        self.result = None
        self.enter = None

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.finish(None)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.enter is not None:
            self.enter()
        else:
            super().keyPressEvent(event)

    def finish(self, value):
        self.result = value
        self.loop.quit()

    def fit(self):
        """Size the card to its contents: wrapped text otherwise makes Qt guess far too tall a card."""
        layout = self.card.layout()
        layout.activate()
        h = layout.totalHeightForWidth(self.card.width()) if layout.hasHeightForWidth() else layout.sizeHint().height()
        self.card.setFixedHeight(max(80, min(h, self.parent().height() - 48)))

    def run(self):
        self.fit()
        self.show()
        self.raise_()
        self.setFocus()
        self.loop.exec()
        self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()
        return self.result


def _actions(overlay, confirm, cancel, kind, value_fn=lambda: True):
    row = QHBoxLayout()
    row.addStretch(1)
    if cancel:
        c = button(cancel, "ghost")
        c.clicked.connect(lambda: overlay.finish(None))
        row.addWidget(c)
    ok = button(confirm, kind)
    ok.setFocusPolicy(Qt.StrongFocus)

    def accept():
        overlay.finish(value_fn())

    ok.clicked.connect(accept)
    overlay.enter = accept
    row.addWidget(ok)
    return row, ok


def ask(title, text, confirm, cancel="Cancel", kind="primary", items=None, note=None, width=520, icon_name=None):
    """A question with a button that says what it does. items: lines naming the files involved.
    Returns True when confirmed."""
    overlay = _Overlay(_host, width)
    head = QHBoxLayout()
    head.setSpacing(10)
    if icon_name:
        ic = QLabel()
        colour = theme.DANGER if kind == "danger" else theme.WARN if icon_name == "warn" else theme.ACCENT
        ic.setPixmap(icons.pixmap(icon_name, colour, 18))
        head.addWidget(ic, 0, Qt.AlignTop)
    t = label(title, "heading")
    t.setWordWrap(True)
    t.setStyleSheet(f"font-size: {theme.text_px('title')}px;")
    head.addWidget(t, 1)
    overlay.v.addLayout(head)
    if text:
        overlay.v.addWidget(label(text, "muted", wrap=True))
    if items:
        lst = QTreeWidget()
        lst.setHeaderHidden(True)
        lst.setRootIsDecorated(False)
        lst.setColumnCount(2)
        lst.setSelectionMode(QTreeWidget.NoSelection)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lst.setTextElideMode(Qt.ElideMiddle)
        lst.header().setSectionResizeMode(0, QHeaderView.Stretch)
        lst.header().setSectionResizeMode(1, QHeaderView.Stretch)  # names and details share the width
        lst.header().setStretchLastSection(False)
        for entry in items[:200]:
            name, detail = entry if isinstance(entry, tuple) else (entry, "")
            item = QTreeWidgetItem([name, detail])
            item.setForeground(1, QColor(theme.FAINT))
            item.setToolTip(0, name)
            lst.addTopLevelItem(item)
        if len(items) > 200:
            lst.addTopLevelItem(QTreeWidgetItem([f"…and {len(items) - 200} more", ""]))
        lst.setFixedHeight(min(240, 8 + theme.ROW_H * min(len(items) + (len(items) > 200), 9)))
        overlay.v.addWidget(lst)
    if note:
        overlay.v.addWidget(caption(note, wrap=True))
    row, _ok = _actions(overlay, confirm, cancel, kind)
    overlay.v.addLayout(row)
    return bool(overlay.run())


def info(title, text, close="Close", kind="secondary", icon_name="info", items=None, width=520):
    """A message with one button."""
    ask(title, text, close, cancel=None, kind=kind, icon_name=icon_name, items=items, width=width)


def error(title, text):
    info(title, text, close="Close", icon_name="error")


def get_text(title, text, value="", confirm="Save", placeholder=""):
    """A question with one text box. Returns the text, or None when cancelled."""
    overlay = _Overlay(_host, 460)
    overlay.v.addWidget(label(title, "heading"))
    if text:
        overlay.v.addWidget(label(text, "muted", wrap=True))
    box = QLineEdit(value)
    box.setPlaceholderText(placeholder)
    box.selectAll()
    overlay.v.addWidget(box)
    row, ok = _actions(overlay, confirm, "Cancel", "primary", value_fn=lambda: box.text().strip() or None)
    box.returnPressed.connect(overlay.enter)
    overlay.v.addLayout(row)
    QTimer.singleShot(0, box.setFocus)
    return overlay.run()


def choose(title, text, options, cancel="Cancel"):
    """A question with several answers: options = [(value, label, kind)]. Returns the value, or None."""
    overlay = _Overlay(_host, 520)
    overlay.v.addWidget(label(title, "heading"))
    if text:
        overlay.v.addWidget(label(text, "muted", wrap=True))
    row = QHBoxLayout()
    row.addStretch(1)
    if cancel:
        c = button(cancel, "ghost")
        c.clicked.connect(lambda: overlay.finish(None))
        row.addWidget(c)
    for i, (value, text_, kind) in enumerate(options):
        b = button(text_, kind)
        b.clicked.connect(lambda _c=False, v=value: overlay.finish(v))
        row.addWidget(b)
        if kind == "primary":
            overlay.enter = lambda v=value: overlay.finish(v)
    overlay.v.addLayout(row)
    return overlay.run()


def review_moves(title, ops, action="Move"):
    """Review before moving (STANDARDS.md): every file's from and to, untick single items, or double-click a
    destination to send it somewhere else. ops: [{"src", "dst_dir", "copy"}]. Returns the chosen ops, or None."""
    overlay = _Overlay(_host, 860)
    overlay.v.addWidget(label(title, "heading"))
    overlay.v.addWidget(label("Nothing moves until you click the button. Untick a file to leave it where it is, or "
                              "double-click its destination to choose another folder.", "muted", wrap=True))
    tree = QTreeWidget()
    tree.setItemDelegate(TintDelegate(tree))
    tree.setHeaderLabels(["File", "From", "To", ""])
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    tree.setTextElideMode(Qt.ElideMiddle)
    h = tree.header()
    h.setStretchLastSection(False)
    h.setSectionResizeMode(0, QHeaderView.Stretch)
    for col, w in ((1, 220), (2, 240), (3, 56)):
        h.setSectionResizeMode(col, QHeaderView.Interactive)
        tree.setColumnWidth(col, w)
    for op in ops:
        src = Path(op["src"])
        item = QTreeWidgetItem([src.name, str(src.parent), str(op["dst_dir"]), "Copy" if op.get("copy") else "Move"])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)
        for c in range(3):
            item.setToolTip(c, item.text(c))
        item.setData(0, Qt.UserRole, op)
        tree.addTopLevelItem(item)
    tree.setFixedHeight(min(420, 30 + theme.ROW_H * min(len(ops), 14)))

    def change(item, column):
        if column == 2:
            chosen = QFileDialog.getExistingDirectory(overlay, "Choose where this file goes", item.text(2))
            if chosen:
                item.setText(2, chosen)
                item.setToolTip(2, chosen)

    tree.itemDoubleClicked.connect(change)
    overlay.v.addWidget(tree)
    count = ElidedLabel("")
    overlay.v.addWidget(count)

    def chosen_ops():
        out = []
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                op = dict(item.data(0, Qt.UserRole))
                op["dst_dir"] = item.text(2)
                out.append(op)
        return out

    row, ok = _actions(overlay, "", "Cancel", "primary", value_fn=lambda: chosen_ops() or None)

    def recount(*_):
        n = len(chosen_ops())
        copies = sum(1 for o in chosen_ops() if o.get("copy"))
        ok.setText(f"{action} {n} file{'s' if n != 1 else ''}")
        ok.setEnabled(n > 0)
        count.setText(f"{n} of {len(ops)} ticked" + (f" · {copies} will be copied, because they belong to "
                                                      f"more than one group" if copies else ""))

    tree.itemChanged.connect(recount)
    recount()
    overlay.v.addLayout(row)
    return overlay.run()


# ----- toasts -----
class Toasts(QObject):
    """Short messages at the bottom right, for "done" and short errors. Long errors go to the log."""

    def __init__(self, parent, bottom_offset=44):
        super().__init__(parent)
        self.parent_widget = parent
        self.offset = bottom_offset
        self.items = []
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._place()
        return False

    def show(self, text, kind="ok", seconds=5):
        frame = QFrame(self.parent_widget)
        frame.setObjectName("toast")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120))
        frame.setGraphicsEffect(shadow)
        h = QHBoxLayout(frame)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)
        ic = QLabel()
        name, colour = {"ok": ("check", theme.OK), "danger": ("error", theme.DANGER),
                        "warn": ("warn", theme.WARN)}.get(kind, ("info", theme.ACCENT))
        ic.setPixmap(icons.pixmap(name, colour, 16))
        h.addWidget(ic)
        lab = label(text, "value", wrap=True)
        lab.setMaximumWidth(380)
        h.addWidget(lab)
        frame.adjustSize()
        frame.show()
        frame.raise_()
        self.items.append(frame)
        self._place()
        QTimer.singleShot(max(4, min(7, seconds)) * 1000, lambda: self._drop(frame))

    def _drop(self, frame):
        if frame in self.items:
            self.items.remove(frame)
            frame.deleteLater()
            self._place()

    def _place(self):
        y = self.parent_widget.height() - self.offset
        for frame in reversed(self.items):
            frame.adjustSize()
            y -= frame.height() + 8
            frame.move(self.parent_widget.width() - frame.width() - 16, y)
            frame.raise_()

"""Shared building blocks: cards, buttons, folder rows, tables, the page layout and thread-safe UI calls."""
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QTreeWidget, QVBoxLayout, QWidget)

import theme


class Bridge(QObject):
    """Background threads hand UI work to the main thread through this, so Qt is only touched there."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run)

    def _run(self, fn):
        try:
            fn()
        except RuntimeError:
            pass  # the page it was for was rebuilt (for example, after an appearance change)


def card():
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def label(text="", role="body", wrap=False):
    w = QLabel(text)
    w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


def muted(text, wrap=False):
    return label(text, "muted", wrap)


def button(text, kind="secondary", icon=None):
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(theme.px(18), theme.px(18)))
    return b


def line_edit(text="", placeholder="", width=None):
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    if width:
        e.setFixedWidth(theme.px(width))
    return e


def make_tree(headers, widths):
    """A table whose columns can be dragged wider or narrower by their heading dividers."""
    tree = QTreeWidget()
    tree.setHeaderLabels(list(headers))
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    tree.setSelectionMode(QTreeWidget.ExtendedSelection)
    tree.header().setStretchLastSection(True)
    tree.header().setMinimumSectionSize(theme.px(70))
    for i, width in enumerate(widths):
        tree.setColumnWidth(i, theme.px(width))
    return tree


def pick_folder(edit, title):
    chosen = QFileDialog.getExistingDirectory(edit, title, edit.text().strip())
    if chosen:
        edit.setText(chosen)
        return True
    return False


def folder_row(grid, row, text, edit, title, on_change=None):
    """Label, path box and Browse button on one row of a QGridLayout (the path box stretches)."""
    grid.addWidget(label(text), row, 0)
    grid.addWidget(edit, row, 1)
    browse = button("Browse")

    def go():
        if pick_folder(edit, title) and on_change:
            on_change()

    browse.clicked.connect(go)
    grid.addWidget(browse, row, 2)
    return browse


class Page(QWidget):
    """A tool page: a title and subtitle, then the page content in a scroll area.
    The content fills the window; it only scrolls when the window is smaller than the content needs."""
    title = ""
    subtitle = ""

    def __init__(self, app):
        super().__init__()
        self.app = app
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(label(self.title, "title"))
        outer.addWidget(muted(self.subtitle, wrap=True))
        outer.addSpacing(theme.px(16))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content.setObjectName("page")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, theme.px(12), 0)
        self.body.setSpacing(theme.px(12))
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        self.build()

    def build(self):
        raise NotImplementedError

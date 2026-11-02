"""Shared building blocks: cards, buttons, folder rows, tables, the page layout and thread-safe UI calls."""
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget)

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer


import settings
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


def toolbar():
    """The bar across the top of a tool: folders, options and the Run button. Returns (frame, rows layout)."""
    frame = QFrame()
    frame.setObjectName("toolbar")
    rows = QVBoxLayout(frame)
    rows.setContentsMargins(theme.px(12), theme.px(10), theme.px(12), theme.px(10))
    rows.setSpacing(theme.px(8))
    return frame, rows


def tool_row():
    row = QHBoxLayout()
    row.setSpacing(theme.px(8))
    return row


def add_folder(row, text, edit, title, on_change=None, stretch=1):
    """Label, path box and Browse button, added to a tool bar row."""
    if text:
        row.addWidget(muted(text))
    row.addWidget(edit, stretch)
    browse = button("Browse")

    def go():
        if pick_folder(edit, title) and on_change:
            on_change()

    browse.clicked.connect(go)
    row.addWidget(browse)
    return browse


def divider():
    """A thin upright line between groups in a tool bar row."""
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedWidth(1)
    return line


def results_bar(summary, *buttons):
    """The line above a results list: a summary on the left, the list's actions on the right."""
    row = QHBoxLayout()
    row.setSpacing(theme.px(8))
    row.addWidget(summary, 1)
    for b in buttons:
        row.addWidget(b)
    return row


def results_panel():
    """The card that holds a results list and fills the rest of the page. Returns (frame, layout)."""
    frame = card()
    v = QVBoxLayout(frame)
    v.setContentsMargins(theme.px(12), theme.px(10), theme.px(12), theme.px(12))
    v.setSpacing(theme.px(8))
    return frame, v


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
        outer.addSpacing(theme.px(2))
        outer.addWidget(muted(self.subtitle, wrap=True))
        outer.addSpacing(theme.px(12))

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


# ----- remembered sizes: splitters and table columns keep the sizes you dragged them to -----
_remembered = {}   # key -> splitter or table header, for the screen currently shown
_save_timer = None


def reset_remembered():
    """Forget the widgets of the screen that is being replaced (their sizes are already saved)."""
    _remembered.clear()


def remember(key, widget, header=False):
    """Restore the saved size of a splitter (or of a table's columns when header=True), and save it
    whenever it is dragged."""
    target = widget.header() if header else widget
    _remembered[key] = target
    saved = settings.load().get("layout", {}).get(key)
    if saved:
        target.restoreState(QByteArray.fromBase64(saved.encode()))
    if header:
        target.sectionResized.connect(lambda *_args: _schedule_save())
    else:
        target.splitterMoved.connect(lambda *_args: _schedule_save())


def _schedule_save():
    global _save_timer
    if _save_timer is None:
        _save_timer = QTimer()
        _save_timer.setSingleShot(True)
        _save_timer.setInterval(400)  # wait until the drag has settled before writing the file
        _save_timer.timeout.connect(_save_now)
    _save_timer.start()


def _save_now():
    layout = dict(settings.load().get("layout", {}))
    for key, target in list(_remembered.items()):
        try:
            layout[key] = bytes(target.saveState().toBase64()).decode()
        except RuntimeError:
            pass  # the widget was replaced since it was remembered
    settings.save({"layout": layout})


# ----- a list of folders with a tick box beside each one -----
REL_PATH = Qt.UserRole


class FolderChecklist(QWidget):
    """Lists folders with a tick box on each. Everything starts ticked; untick the ones to leave out."""

    def __init__(self, title, recursive, key):
        super().__init__()
        self.recursive = recursive
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.px(8))
        head = QHBoxLayout()
        head.setSpacing(theme.px(8))
        head.addWidget(label(title, "heading"))
        self.count = muted("")
        head.addWidget(self.count)
        head.addStretch(1)
        all_btn = button("Select all")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = button("Select none")
        none_btn.clicked.connect(lambda: self._set_all(False))
        head.addWidget(all_btn)
        head.addWidget(none_btn)
        v.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder"])
        self.tree.setRootIsDecorated(recursive)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._item_changed)
        remember(key, self.tree, header=True)
        v.addWidget(self.tree, 1)

    def clear(self, message=""):
        self.tree.clear()
        self.count.setText(message)

    def load(self, root):
        """List the folders in root (and their subfolders, when recursive)."""
        self.tree.blockSignals(True)
        self.tree.clear()
        try:
            if self.recursive:
                self._add_children(self.tree, Path(root), "")
            else:
                for name in self._subdirs(Path(root)):
                    self._add_row(self.tree, name, name)
        except OSError as exc:
            self.count.setText(f"Could not read this folder: {exc}")
            self.tree.blockSignals(False)
            return
        self.tree.blockSignals(False)
        self.tree.expandToDepth(0)
        self._update_count()

    def _subdirs(self, folder):
        return sorted(e.name for e in os.scandir(folder) if e.is_dir(follow_symlinks=False))

    def _add_children(self, parent, folder, prefix):
        for name in self._subdirs(folder):
            rel = f"{prefix}{name}" if not prefix else f"{prefix}/{name}"
            item = self._add_row(parent, name, rel)
            self._add_children(item, folder / name, rel)

    def _add_row(self, parent, name, rel):
        item = QTreeWidgetItem([name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)
        item.setData(0, REL_PATH, rel)
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def _all_items(self):
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            yield it.value()
            it += 1

    def _item_changed(self, item, _column):
        # Ticking or unticking a folder does the same to everything inside it.
        self.tree.blockSignals(True)
        state = item.checkState(0)
        stack = [item]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                child.setCheckState(0, state)
                stack.append(child)
        self.tree.blockSignals(False)
        self._update_count()

    def _set_all(self, checked):
        self.tree.blockSignals(True)
        for item in self._all_items():
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_count()

    def _update_count(self):
        items = list(self._all_items())
        chosen = sum(1 for i in items if i.checkState(0) == Qt.Checked)
        self.count.setText(f"{chosen} of {len(items)} selected" if items else "No folders here")

    def checked_names(self):
        """Names (or paths relative to the folder, when recursive) of the ticked folders."""
        return {i.data(0, REL_PATH) for i in self._all_items() if i.checkState(0) == Qt.Checked}

    def unchecked_paths(self):
        return {i.data(0, REL_PATH) for i in self._all_items() if i.checkState(0) != Qt.Checked}

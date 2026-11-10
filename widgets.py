"""Shared building blocks (DESIGN.md, "Components"): buttons, fields, segmented controls, tags, banners, empty
states, toolbars, panels, tick-aware lists, the page layout, remembered sizes and thread-safe UI calls."""
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout,
                               QLineEdit, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QWidget)

import icons
import settings
import theme


class Bridge(QObject):
    """Background threads hand UI work to the main thread through this, so Qt is only touched there."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())


# ----- text -----
def label(text="", role="body", wrap=False):
    w = QLabel(text)
    w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


def muted(text, wrap=False):
    return label(text, "muted", wrap)


def caption(text, wrap=False):
    return label(text, "caption", wrap)


def tag(text, kind="acc"):
    """A 20 px round status label: kind is acc, ok, warn, danger or plain."""
    w = QLabel(text)
    w.setProperty("tag", kind)
    w.setAlignment(Qt.AlignCenter)
    return w


def set_tag(widget, text, kind):
    widget.setText(text)
    widget.setProperty("tag", kind)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """One line of text that shortens with "..." instead of pushing the window wider."""

    def __init__(self, text="", role="muted", mode=Qt.ElideRight):
        super().__init__(text)
        self.setProperty("role", role)
        self._full = text
        self._mode = mode
        self.setToolTip(text)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text):
        self._full = text
        self.setToolTip(text if len(text) > 30 else "")
        self._elide()

    def text_full(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(self._full, self._mode, max(1, self.contentsRect().width()))
        QLabel.setText(self, shown)


# ----- controls -----
def button(text, kind="secondary", icon=None, tip=""):
    """kind: primary (one per toolbar), secondary, ghost, danger-ghost, danger (only in dialogs)."""
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.TabFocus)  # the focus ring shows when moving with Tab, not after every click
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(theme.ICON, theme.ICON))
    if tip:
        b.setToolTip(tip)
    if kind == "primary":
        theme.set_glow(b)
    return b


def set_kind(b, kind):
    b.setProperty("kind", kind)
    repolish(b)
    theme.set_glow(b) if kind == "primary" else b.setGraphicsEffect(None)


def line_edit(text="", placeholder="", width=None, mono=False):
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    if width:
        e.setFixedWidth(width)
    if mono:
        e.setObjectName("mono")
    return e


class Segmented(QFrame):
    """A field-coloured track with buttons; the chosen one is raised. Counts sit faint after the label."""
    changed = Signal(object)

    def __init__(self, options, value=None):
        """options: [(value, label)]."""
        super().__init__()
        self.setObjectName("seg")
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self.labels = {}
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("segbtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            self.group.addButton(b)
            h.addWidget(b)
            self.buttons[key] = b
            self.labels[key] = text
        self._value = None
        self.set_value(value if value is not None else options[0][0], emit=False)

    def _pick(self, key):
        if key != self._value:
            self._value = key
            self.changed.emit(key)

    def value(self):
        return self._value

    def set_value(self, key, emit=False):
        if key in self.buttons:
            self.buttons[key].setChecked(True)
            changed = key != self._value
            self._value = key
            if emit and changed:
                self.changed.emit(key)

    def set_count(self, key, count):
        """"Not done 8": the count shows after the label."""
        if key in self.buttons:
            self.buttons[key].setText(self.labels[key] if count is None else f"{self.labels[key]}  {count}")


def field_label(text):
    w = muted(text)
    w.setFixedWidth(theme.LABEL_W)
    return w


def divider(height=18):
    """A thin upright line between groups in a toolbar row."""
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedSize(1, height)
    return line


def hline():
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def pick_folder(parent, title, start=""):
    return QFileDialog.getExistingDirectory(parent, title, start or "")


def add_folder(row, text, edit, title, on_change=None, stretch=1):
    """Label, path box and Browse button, added to a toolbar row."""
    if text:
        row.addWidget(field_label(text))
    edit.setMinimumWidth(120)
    row.addWidget(edit, stretch)
    browse = button("Browse")

    def go():
        chosen = pick_folder(edit, title, edit.text().strip())
        if chosen:
            edit.setText(chosen)
            if on_change:
                on_change()

    browse.clicked.connect(go)
    row.addWidget(browse)
    return browse


# ----- panels -----
def panel(name="panel"):
    frame = QFrame()
    frame.setObjectName(name)
    return frame


card = panel


def toolbar():
    """The toolbar panel: row one holds the main input and the main action, row two its settings."""
    frame = panel("toolbar")
    rows = QVBoxLayout(frame)
    rows.setContentsMargins(theme.PAD, theme.PAD - 2, theme.PAD, theme.PAD - 2)
    rows.setSpacing(theme.GAP - 2)
    return frame, rows


def tool_row():
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.GAP)
    return row


def wrap_row():
    """A toolbar row that wraps onto a second line on narrow windows instead of scrolling sideways."""
    host = QWidget()
    flow = FlowLayout(host, spacing=theme.GAP, vspacing=theme.GAP - 2, align_center=True)
    return host, flow


def results_bar(summary, *widgets):
    """The summary line over a work area: the summary on the left, filters, views and buttons on the right."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.GAP - 2)
    row.addWidget(summary, 1)
    for w in widgets:
        if w is None:
            row.addSpacing(theme.GAP)
        else:
            row.addWidget(w)
    return row


def results_panel():
    """The panel that holds a work area and fills the rest of the page. Returns (frame, layout)."""
    frame = panel()
    v = QVBoxLayout(frame)
    v.setContentsMargins(theme.PAD, theme.PAD - 2, theme.PAD, theme.PAD)
    v.setSpacing(theme.GAP - 2)
    return frame, v


class Banner(QFrame):
    """One line: an icon, a bold lead, a sentence and one button. For "needs setting up first" states."""

    def __init__(self, lead, sentence, action_text=None, action=None, icon_name="info"):
        super().__init__()
        self.setObjectName("banner")
        h = QHBoxLayout(self)
        h.setContentsMargins(theme.PAD, 6, 6, 6)
        h.setSpacing(theme.GAP)
        self.icon = QLabel()
        self.icon.setPixmap(icons.pixmap(icon_name, theme.ACCENT, 16))
        h.addWidget(self.icon)
        self.lead = label(lead, "heading")
        h.addWidget(self.lead)
        self.text = ElidedLabel(sentence)
        h.addWidget(self.text, 1)
        self.button = None
        if action_text:
            self.button = button(action_text)
            if action:
                self.button.clicked.connect(action)
            h.addWidget(self.button)

    def set(self, lead, sentence, action_text=None):
        self.lead.setText(lead)
        self.text.setText(sentence)
        if self.button is not None and action_text:
            self.button.setText(action_text)


class EmptyState(QWidget):
    """A 28 px faint icon, one sentence on what goes here, and the button that fills it."""

    def __init__(self, icon_name, sentence, action_text=None, action=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)
        self._icon_name = icon_name
        self.icon.setPixmap(icons.pixmap(icon_name, theme.FAINT, 28))
        v.addWidget(self.icon)
        self.text = label(sentence, "empty", wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setMaximumWidth(420)
        v.addWidget(self.text, 0, Qt.AlignCenter)
        self.button = None
        if action_text:
            self.button = button(action_text)
            if action:
                self.button.clicked.connect(action)
            v.addWidget(self.button, 0, Qt.AlignCenter)
        theme.on_change(self._recolour)

    def _recolour(self):
        try:
            self.icon.setPixmap(icons.pixmap(self._icon_name, theme.FAINT, 28))
        except RuntimeError:
            pass

    def set_text(self, sentence, action_text=None):
        self.text.setText(sentence)
        if self.button is not None:
            self.button.setVisible(bool(action_text))
            if action_text:
                self.button.setText(action_text)


# ----- lists with tick boxes (DESIGN.md, "Selecting and ticking") -----
def make_tree(headers, widths, ticks=False):
    """A table whose first column takes the spare width, so it never scrolls sideways.
    The other columns keep their width and can be dragged wider or narrower."""
    tree = QTreeWidget()
    tree.setItemDelegate(TintDelegate(tree))
    tree.setHeaderLabels(list(headers))
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    tree.setSelectionMode(QTreeWidget.SingleSelection if ticks else QTreeWidget.ExtendedSelection)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    tree.setTextElideMode(Qt.ElideMiddle)
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(0, QHeaderView.Stretch)
    header.setMinimumSectionSize(48)
    header.setHighlightSections(False)
    for i, width in enumerate(widths):
        tree.setColumnWidth(i, width)
    if ticks:
        Ticking(tree)
    return tree


def fit(source, size, dpr=1.0):
    """source (QPixmap or QImage) scaled to fit size (logical pixels), drawn at the screen's full sharpness."""
    from PySide6.QtCore import QSize as _QSize
    target = _QSize(max(1, int(size.width() * dpr)), max(1, int(size.height() * dpr)))
    out = source.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out.setDevicePixelRatio(dpr)
    return out


class TintDelegate(QStyledItemDelegate):
    """Paints a row's tick tint under the item and the selected row's accent outline over it, across the
    whole row (the style sheet's item rules would otherwise hide the tint and cut the outline at each cell)."""

    def paint(self, painter, option, index):
        r = option.rect
        left = 0 if index.column() == 0 else r.left()  # include a tree's indent and branch area
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.fillRect(QRect(left, r.top(), r.right() - left + 1, r.height()), bg)
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            view = self.parent()
            painter.save()
            painter.setPen(QPen(QColor(theme.ACCENT), 1))
            right = r.right()
            if hasattr(view, "header"):
                cols = view.header().count()
            elif hasattr(view, "horizontalHeader"):
                cols = view.horizontalHeader().count()
            else:
                cols = 1
            last = index.column() == cols - 1
            if last and view is not None:
                right = view.viewport().width() - 1
            painter.drawLine(left, r.top(), right, r.top())
            painter.drawLine(left, r.bottom(), right, r.bottom())
            if index.column() == 0:
                painter.drawLine(0, r.top(), 0, r.bottom())
            if last:
                painter.drawLine(right, r.top(), right, r.bottom())
            painter.restore()


class Ticking(QObject):
    """Adds the suite's ticking to a QTreeWidget: a click selects; Ctrl+click or the tick box ticks;
    Shift with either ticks the range from the last ticked item; ticked rows get a faint accent tint.
    With the "click to tick" option, a plain click ticks instead."""
    ticks_changed = Signal()

    def __init__(self, tree):
        super().__init__(tree)
        self.tree = tree
        self.anchor = None
        tree.ticking = self
        self.delegate = TintDelegate(tree)
        tree.setItemDelegate(self.delegate)
        tree.viewport().installEventFilter(self)
        tree.itemChanged.connect(self._changed)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            item = self.tree.itemAt(event.position().toPoint())
            if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
                return False
            mods = event.modifiers()
            click_ticks = settings.load().get("click_ticks", False)
            if mods & Qt.ShiftModifier and self.anchor is not None:
                self._tick_range(self.anchor, item)
                self.tree.setCurrentItem(item)
                return True
            if mods & Qt.ControlModifier or click_ticks:
                self._toggle(item)
                self.tree.setCurrentItem(item)
                return True
        return False

    def _toggle(self, item):
        item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)
        self.anchor = item

    def _visible_items(self):
        it = QTreeWidgetItemIterator(self.tree)
        out = []
        while it.value():
            item = it.value()
            if not item.isHidden() and item.flags() & Qt.ItemIsUserCheckable:
                out.append(item)
            it += 1
        return out

    def _tick_range(self, a, b):
        items = self._visible_items()
        try:
            i, j = sorted((items.index(a), items.index(b)))
        except ValueError:
            return
        self.tree.blockSignals(True)
        for item in items[i:j + 1]:
            item.setCheckState(0, Qt.Checked)
            self._tint(item)
        self.tree.blockSignals(False)
        self.ticks_changed.emit()

    def _changed(self, item, column):
        if column == 0:
            self.anchor = item
            self._tint(item)
            self.ticks_changed.emit()

    def _tint(self, item):
        from PySide6.QtGui import QBrush, QColor
        ticked = item.checkState(0) == Qt.Checked
        brush = QBrush(QColor(theme.TINT_TICK)) if ticked else QBrush()
        for c in range(self.tree.columnCount()):
            item.setBackground(c, brush)

    def retint(self):
        for item in self._visible_items():
            self._tint(item)

    def tick_all(self, on=True):
        self.tree.blockSignals(True)
        for item in self._visible_items():
            item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            self._tint(item)
        self.tree.blockSignals(False)
        self.ticks_changed.emit()

    def ticked(self):
        return [i for i in self._visible_items() if i.checkState(0) == Qt.Checked]


# ----- the page -----
class Page(QWidget):
    """A screen: a one-line header (title, then what it does), then the page content.
    The content always fits the window; lists scroll inside themselves, the page never scrolls sideways.
    H hides self.panels (toolbars and side panels) so only the work shows; / focuses self.filter_box."""
    title = ""
    subtitle = ""
    icon = "logo"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.panels = []
        self.filter_box = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.GAP)
        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(2, 0, 0, 0)
        head.setSpacing(12)
        head.addWidget(label(self.title, "title"))
        self.subtitle_label = ElidedLabel(self.subtitle)
        head.addWidget(self.subtitle_label, 1)
        self.header_right = QHBoxLayout()
        self.header_right.setSpacing(theme.GAP)
        head.addLayout(self.header_right)
        outer.addWidget(self.header)
        self.banners = QVBoxLayout()
        self.banners.setSpacing(theme.GAP)
        outer.addLayout(self.banners)

        self.content = QWidget()
        self.content.setObjectName("page")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(theme.GAP)
        outer.addWidget(self.content, 1)
        self.build()

    def build(self):
        raise NotImplementedError

    def set_panels_hidden(self, hidden):
        self.header.setVisible(not hidden)
        for w in self.panels:
            w.setVisible(not hidden)

    def shown(self):
        """Called when the page comes on screen."""

    def queue_changed(self, busy):
        """Called when a job starts or ends, so main buttons can say "Add ... to the queue"."""

    def zoom(self, step):
        """+ / − and Ctrl+wheel: make whatever is in view bigger or smaller."""

    def tick_all(self):
        """Ctrl+A: tick everything shown."""

    def step(self, delta):
        """← → PgUp PgDn: previous / next item. Home / End: first / last (delta = -inf / inf)."""


# ----- a layout that wraps -----
class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto a new row when the width runs out, so rows of cards and
    toolbar rows never need sideways scrolling."""

    def __init__(self, parent=None, spacing=8, vspacing=None, align_center=False):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._vspacing = spacing if vspacing is None else vspacing
        self._center = align_center
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, move):
        x, y, line_h = rect.x(), rect.y(), 0
        line = []
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                if move and self._center:
                    self._center_line(line, line_h)
                x, y, line_h, line = rect.x(), y + line_h + self._vspacing, 0, []
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
                line.append(item)
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        if move and self._center:
            self._center_line(line, line_h)
        return y + line_h - rect.y()

    @staticmethod
    def _center_line(line, line_h):
        for item in line:
            g = item.geometry()
            item.setGeometry(QRect(g.x(), g.y() + (line_h - g.height()) // 2, g.width(), g.height()))


# ----- remembered sizes: splitters and table columns keep the sizes you dragged them to -----
_remembered = {}
_save_timer = None


def reset_remembered():
    _remembered.clear()


def remember(key, widget, header=False):
    """Restore the saved size of a splitter (or of a table's columns when header=True), and save it
    whenever it is dragged."""
    key = "v4:" + key  # sizes saved before version 2 are left behind
    target = widget.header() if header else widget
    _remembered[key] = target
    saved = settings.load().get("layout", {}).get(key)
    if saved:
        target.restoreState(QByteArray.fromBase64(saved.encode()))
    if header:
        target.sectionResized.connect(lambda *_args: _schedule_save())
    else:
        target.splitterMoved.connect(lambda *_args: _schedule_save())


def remembered(key):
    return ("v4:" + key) in settings.load().get("layout", {})


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


# ----- a list of folders with a tick box beside each one (Zip, Copy folder structure) -----
REL_PATH = Qt.UserRole


class FolderChecklist(QWidget):
    """Lists folders with a tick box on each. Everything starts ticked; untick the ones to leave out."""
    changed = Signal()

    def __init__(self, title, recursive, key, empty_text, empty_action=None, empty_button=None):
        super().__init__()
        self.recursive = recursive
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.GAP - 2)
        self.count = ElidedLabel("")
        all_btn = button("Tick all", "ghost")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = button("Untick all", "ghost")
        none_btn.clicked.connect(lambda: self._set_all(False))
        v.addLayout(results_bar(self.count, all_btn, none_btn))
        self.tree = QTreeWidget()
        self.tree.setItemDelegate(TintDelegate(self.tree))
        self.tree.setHeaderLabels([title])
        self.tree.setRootIsDecorated(recursive)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.itemChanged.connect(self._item_changed)
        v.addWidget(self.tree, 1)
        self.empty = EmptyState("folder", empty_text, empty_button, empty_action)
        v.addWidget(self.empty, 1)
        self.tree.hide()

    def clear(self, message=""):
        self.tree.clear()
        self.count.setText(message)
        self.tree.hide()
        self.empty.show()

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
            self.tree.blockSignals(False)
            self.clear(f"This folder couldn't be read: {exc}")
            return
        self.tree.blockSignals(False)
        self.tree.expandToDepth(0)
        has = self.tree.topLevelItemCount() > 0
        self.tree.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.empty.set_text("This folder has no folders inside it.")
        self._update_count()

    def _subdirs(self, folder):
        return sorted(e.name for e in os.scandir(folder) if e.is_dir(follow_symlinks=False))

    def _add_children(self, parent, folder, prefix):
        for name in self._subdirs(folder):
            rel = name if not prefix else f"{prefix}/{name}"
            item = self._add_row(parent, name, rel)
            self._add_children(item, folder / name, rel)

    def _add_row(self, parent, name, rel):
        item = QTreeWidgetItem([name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)
        item.setData(0, REL_PATH, rel)
        item.setIcon(0, icons.icon("folder", theme.FAINT, 16))
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

    def tick_all(self):
        self._set_all(True)

    def _update_count(self):
        items = list(self._all_items())
        chosen = sum(1 for i in items if i.checkState(0) == Qt.Checked)
        self.count.setText(f"{chosen} of {len(items)} folders ticked" if items else "No folders here")
        self.changed.emit()

    def ticked_count(self):
        return sum(1 for i in self._all_items() if i.checkState(0) == Qt.Checked)

    def checked_names(self):
        """Names (or paths relative to the folder, when recursive) of the ticked folders."""
        return {i.data(0, REL_PATH) for i in self._all_items() if i.checkState(0) == Qt.Checked}

    def unchecked_paths(self):
        return {i.data(0, REL_PATH) for i in self._all_items() if i.checkState(0) != Qt.Checked}

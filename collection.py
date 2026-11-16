"""Collections of files (DESIGN.md, "Collections"): List, Grid and Gallery views of the same items, a folder
tree with counts, sorting, a size slider, and the suite's selecting and ticking.

- A click selects (accent outline). Ctrl+click or the tick box ticks; Shift ticks a range. Ticked items get a
  faint accent tint. With the "click ticks" option a plain click ticks.
- Actions use the ticked items, or the selected one when nothing is ticked.
- Double-click opens Gallery: one item, nothing drawn over it, with a 300 px side panel.
"""
import os
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QEvent, QItemSelectionModel, QModelIndex, QObject, QRect, QSize,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListView, QPushButton, QScrollArea, QSlider, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QTableView, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import fileops
import icons
import preview
import settings
import theme
import thumbs
from widgets import fit as widgets_fit
from widgets import ElidedLabel, EmptyState, Segmented, TintDelegate, button, label, remember, repolish

ITEM = Qt.UserRole + 10
SORT = Qt.UserRole + 11
STATUS_KIND = {"Done": "ok", "Failed": "danger", "Working": "acc", "Queued": "plain"}
GRID_MIN, GRID_MAX = 110, 480


def norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


class Column:
    def __init__(self, key, title, width=90, text=None, sort=None, align=Qt.AlignLeft):
        self.key, self.title, self.width = key, title, width
        self.text = text or (lambda item, k=key: "" if item.get(k) is None else str(item.get(k)))
        self.sort = sort or (lambda item, k=key: item.get(k) if item.get(k) is not None else "")
        self.align = align


def name_column():
    return Column("name", "Name", 240, sort=lambda i: i["name"].lower())


def size_column():
    return Column("size", "Size", 84, text=lambda i: fileops.human_size(i["size"]) if i.get("size") else "",
                  sort=lambda i: i.get("size") or 0, align=Qt.AlignRight)


def folder_column():
    return Column("folder", "Folder", 180, text=lambda i: i.get("rel_folder", ""),
                  sort=lambda i: i.get("rel_folder", "").lower())


def status_column():
    return Column("status", "Status", 84, sort=lambda i: ["", "Queued", "Working", "Done", "Failed"].index(
        i.get("status", "")) if i.get("status", "") in ("", "Queued", "Working", "Done", "Failed") else 0)


def make_item(path, root, **extra):
    """An item for a file found under root."""
    p = Path(path)
    try:
        st = p.stat()
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    try:
        rel = "." if Path(root).is_file() else p.parent.relative_to(root).as_posix()
    except ValueError:
        rel = str(p.parent)
    item = {"path": str(p), "name": p.name, "root": str(root), "rel_folder": "" if rel == "." else rel,
            "size": size, "mtime": mtime, "ticked": False, "status": "", "detail": ""}
    item.update(extra)
    return item


# ----- the model -----
class Model(QAbstractTableModel):
    ticks_changed = Signal()

    def __init__(self, columns):
        super().__init__()
        self.columns = columns
        self.items = []
        self.rows = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns[section].title
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int(self.columns[section].align | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        col = self.columns[index.column()]
        if role == Qt.DisplayRole:
            return col.text(item)
        if role == Qt.ToolTipRole:
            if index.column() == 0:
                return item["path"]
            if col.key == "status" and item.get("detail"):
                return item["detail"]
            return col.text(item)
        if role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if item["ticked"] else Qt.Unchecked
        if role == Qt.BackgroundRole and item["ticked"]:
            return QColor(theme.TINT_TICK)
        if role == Qt.ForegroundRole:
            if col.key == "status":
                return QColor({"Done": theme.OK, "Failed": theme.DANGER, "Working": theme.ACCENT}.get(
                    item.get("status"), theme.FAINT))
            if item.get("own") and col.key in ("gif", "settings"):
                return QColor(theme.ACCENT)  # a video's own values show in the accent
            if index.column() > 0:
                return QColor(theme.SEC)
        if role == Qt.TextAlignmentRole:
            return int(col.align | Qt.AlignVCenter)
        if role == ITEM:
            return item
        if role == SORT:
            return col.sort(item)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == 0:
            self.set_ticked([self.items[index.row()]], Qt.CheckState(value) == Qt.Checked)
            return True
        return False

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            f |= Qt.ItemIsUserCheckable
        return f

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.rows = {norm(i["path"]): n for n, i in enumerate(self.items)}
        self.endResetModel()
        self.ticks_changed.emit()

    def add(self, items):
        if not items:
            return
        start = len(self.items)
        self.beginInsertRows(QModelIndex(), start, start + len(items) - 1)
        for n, item in enumerate(items):
            self.items.append(item)
            self.rows[norm(item["path"])] = start + n
        self.endInsertRows()

    def remove(self, paths):
        gone = {norm(p) for p in paths}
        if not any(g in self.rows for g in gone):
            return
        self.set_items([i for i in self.items if norm(i["path"]) not in gone])

    def find(self, path):
        row = self.rows.get(norm(path))
        return None if row is None else self.items[row]

    def changed(self, item):
        row = self.rows.get(norm(item["path"]))
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.columns) - 1))

    def set_ticked(self, items, on):
        for item in items:
            item["ticked"] = on
            self.changed(item)
        self.ticks_changed.emit()


class Proxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(SORT)
        self.folder = None  # (root, relative folder or None)
        self.text = ""

    def set_folder(self, folder):
        self.folder = folder
        self.invalidateFilter()

    def set_text(self, text):
        self.text = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        item = self.sourceModel().items[row]
        if self.folder:
            root, rel = self.folder
            if norm(item["root"]) != norm(root):
                return False
            if rel and not (item["rel_folder"] == rel or item["rel_folder"].startswith(rel + "/")):
                return False
        if self.text and self.text not in item["name"].lower():
            return False
        return True

    def lessThan(self, a, b):
        x, y = a.data(SORT), b.data(SORT)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


# ----- the folder tree -----
class FolderTree(QTreeWidget):
    """Every folder you added, with the folders inside it that hold items and how many. Click one to show only
    its items (ticks are kept). × takes a folder off the list."""
    picked = Signal(object)        # (root, rel) or None for all
    remove_root = Signal(str)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(3)
        self.setRootIsDecorated(True)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideMiddle)
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(1, 44)
        self.setColumnWidth(2, 26)
        self.itemClicked.connect(self._clicked)
        self.setItemDelegate(TintDelegate(self))
        self._roots = []
        self.file_icon = "image"

    def fill(self, roots, items):
        current = self.currentItem().data(0, Qt.UserRole) if self.currentItem() else None
        self.clear()
        self._roots = list(roots)
        everything = QTreeWidgetItem(["All folders", str(len(items)), ""])
        everything.setData(0, Qt.UserRole, None)
        everything.setIcon(0, icons.icon("folder", theme.SEC, 16))
        self._style_count(everything)
        self.addTopLevelItem(everything)
        counts = {}
        for item in items:
            key = norm(item["root"])
            counts.setdefault(key, {}).setdefault("", 0)
            counts[key][""] += 1
            parts = item["rel_folder"].split("/") if item["rel_folder"] else []
            for n in range(1, len(parts) + 1):
                rel = "/".join(parts[:n])
                counts[key][rel] = counts[key].get(rel, 0) + 1
        chosen = everything
        for root in roots:
            c = counts.get(norm(root), {})
            node = QTreeWidgetItem([Path(root).name or str(root), str(c.get("", 0)), ""])
            node.setToolTip(0, str(root))
            node.setData(0, Qt.UserRole, (str(root), None))
            node.setIcon(0, icons.icon(self.file_icon if Path(root).is_file() else "folder", theme.ACCENT, 16))
            self._style_count(node)
            self.addTopLevelItem(node)
            x = QPushButton()
            x.setProperty("kind", "ghost")
            x.setIcon(icons.icon("x", theme.FAINT, 14))
            x.setFixedSize(22, 22)
            x.setStyleSheet("min-height: 20px; max-height: 20px; padding: 0px;")
            x.setToolTip(f"Take {Path(root).name} off the list (nothing on disk changes)")
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.clicked.connect(lambda _c=False, r=str(root): self.remove_root.emit(r))
            self.setItemWidget(node, 2, x)
            nodes = {"": node}
            for rel in sorted(k for k in c if k):
                parent = nodes.get(rel.rpartition("/")[0], node)
                child = QTreeWidgetItem([rel.rpartition("/")[2], str(c[rel]), ""])
                child.setData(0, Qt.UserRole, (str(root), rel))
                child.setToolTip(0, rel)
                self._style_count(child)
                parent.addChild(child)
                nodes[rel] = child
            node.setExpanded(True)
            if current and current == (str(root), None):
                chosen = node
            for rel, n in nodes.items():
                if current and current == (str(root), rel or None):
                    chosen = n
        self.setCurrentItem(chosen)
        if chosen is everything and current is not None:
            self.picked.emit(None)  # the folder that was picked is gone

    def _style_count(self, node):
        node.setForeground(1, QColor(theme.FAINT))
        node.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)

    def _clicked(self, node, _column):
        self.picked.emit(node.data(0, Qt.UserRole))


# ----- ticking in List and Grid -----
class TickFilter(QObject):
    """Event filter for a view's viewport: Ctrl+click ticks, Shift+click ticks a range, the Grid's corner box
    ticks, and "click ticks" makes a plain click tick."""

    def __init__(self, coll, view, grid=False):
        super().__init__(view)
        self.coll, self.view, self.grid = coll, view, grid
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            index = self.view.indexAt(event.position().toPoint())
            if index.isValid():
                self.coll.open_gallery(index)
                return True
        if event.type() != QEvent.MouseButtonPress or event.button() != Qt.LeftButton:
            return False
        pos = event.position().toPoint()
        index = self.view.indexAt(pos)
        if not index.isValid():
            return False
        item = self.coll.item_at(index)
        mods = event.modifiers()
        if mods & Qt.ShiftModifier and self.coll.anchor is not None:
            self.coll.tick_range(self.coll.anchor, item)
            self.coll.select(item)
            return True
        on_box = False
        if self.grid:
            rect = self.view.visualRect(index)
            on_box = QRect(rect.x() + 10, rect.y() + 10, 22, 22).contains(pos)
        else:
            on_box = index.column() == 0 and pos.x() - self.view.visualRect(index).x() < 26
        if on_box or mods & Qt.ControlModifier or settings.load().get("click_ticks", False):
            self.coll.toggle(item)
            self.coll.select(item)
            return True
        return False


# ----- Grid -----
class GridDelegate(QStyledItemDelegate):
    def __init__(self, coll):
        super().__init__()
        self.coll = coll

    def sizeHint(self, option, index):
        s = self.coll.grid_size
        return QSize(s + 12, int(s * 0.75) + 12 + 40)

    def paint(self, p, option, index):
        item = self.coll.item_at(index)
        s = self.coll.grid_size
        r = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        card = QPainterPath()
        card.addRoundedRect(r, theme.R_PANEL, theme.R_PANEL)
        p.fillPath(card, QColor(theme.TINT_TICK if item["ticked"] else theme.RAISED))
        p.setPen(QPen(QColor(theme.OUTLINE if selected else theme.LINE), theme.OUTLINE_W if selected else 1))
        p.drawPath(card)
        thumb = QRect(r.x() + 6, r.y() + 6, r.width() - 12, int(s * 0.75))
        clip = QPainterPath()
        clip.addRoundedRect(thumb, theme.R_CONTROL, theme.R_CONTROL)
        p.fillPath(clip, QColor(theme.STAGE))
        image = self.coll.thumbs.get(item["path"])
        if image is not None:
            dpr = p.device().devicePixelRatioF()
            scaled = widgets_fit(image, thumb.size(), dpr)
            logical = scaled.deviceIndependentSize()
            x = thumb.x() + int((thumb.width() - logical.width()) // 2)
            y = thumb.y() + int((thumb.height() - logical.height()) // 2)
            p.setClipPath(clip)
            p.drawImage(x, y, scaled)
            p.setClipping(False)
        else:
            p.drawPixmap(thumb.center().x() - 12, thumb.center().y() - 12,
                         icons.pixmap(self.coll.kind_icon, theme.FAINT, 24))
        # the tick box, on the thumbnail's corner
        box = QRect(r.x() + 10, r.y() + 10, 18, 18)
        path = QPainterPath()
        path.addRoundedRect(box, 4, 4)
        if item["ticked"]:
            p.fillPath(path, theme.qgradient(18, 18))
            p.drawPixmap(box.x() + 2, box.y() + 2, icons.pixmap("check", theme.ON_ACCENT, 14))
        else:
            p.fillPath(path, QColor(0, 0, 0, 110))
            p.setPen(QPen(QColor(255, 255, 255, 150), 1))
            p.drawPath(path)
        status = item.get("status")
        if status:
            colour = {"Done": theme.OK, "Failed": theme.DANGER, "Working": theme.ACCENT}.get(status, theme.SEC)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(status) + 14
            tag = QRect(thumb.right() - w - 4, thumb.bottom() - 22, w, 18)
            tp = QPainterPath()
            tp.addRoundedRect(tag, 9, 9)
            p.fillPath(tp, QColor(theme.PANEL))
            p.setPen(QColor(colour))
            p.setFont(theme.font("caption"))
            p.drawText(tag, Qt.AlignCenter, status)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font("body"))
        text_r = QRect(r.x() + 8, thumb.bottom() + 6, r.width() - 16, 18)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(item["name"], Qt.ElideMiddle, text_r.width()))
        p.setPen(QColor(theme.FAINT))
        p.setFont(theme.font("caption"))
        sub_r = QRect(r.x() + 8, text_r.bottom() + 1, r.width() - 16, 16)
        p.drawText(sub_r, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.coll.subline(item), Qt.ElideRight, sub_r.width()))
        p.restore()


# ----- Gallery -----
class Stage(QLabel):
    """The picture, fitted or at actual size, with nothing drawn over it."""

    def __init__(self):
        super().__init__()
        self.setObjectName("stage")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 160)
        self.source = None
        self.fit = True

    def show_image(self, pixmap):
        self.source = pixmap
        self._refresh()

    def show_message(self, text):
        self.source = None
        self.setPixmap(QPixmap())
        self.setText(text)
        self.setProperty("role", "empty")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if self.source is None or self.source.isNull():
            return
        if self.fit:
            size = self.size() - QSize(4, 4)
            self.setPixmap(widgets_fit(self.source, size, self.devicePixelRatioF()))
        else:
            self.setPixmap(self.source)  # actual size: the middle shows when it's bigger than the stage


class Gallery(QWidget):
    def __init__(self, coll):
        super().__init__()
        self.coll = coll
        self.item = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP)
        self.stack = QStackedWidget()
        self.stage = Stage()
        self.stack.addWidget(self.stage)
        self.player = preview.Player() if coll.kind == "video" else None
        if self.player is not None:
            self.stack.addWidget(self.player)
        h.addWidget(self.stack, 1)
        side = QFrame()
        side.setObjectName("panel")
        side.setMinimumWidth(280)
        v = QVBoxLayout(side)
        v.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        v.setSpacing(theme.GAP)
        self.name = label("", "heading", wrap=True)
        v.addWidget(self.name)
        self.position = label("", "caption")
        v.addWidget(self.position)
        self.tick = QCheckBox("Ticked")
        self.tick.setToolTip("Tick or untick this item (Space)")
        self.tick.clicked.connect(lambda on: self.item and self.coll.model.set_ticked([self.item], on))
        v.addWidget(self.tick)
        self.details = QGridLayout()
        self.details.setHorizontalSpacing(10)
        self.details.setVerticalSpacing(3)
        self.details.setColumnStretch(1, 1)
        v.addLayout(self.details)
        self.actions = QVBoxLayout()
        self.actions.setSpacing(6)
        v.addLayout(self.actions)
        for text, fn in coll.gallery_actions:
            b = button(text)
            b.clicked.connect(lambda _c=False, f=fn: self.item and f(self.item))
            self.actions.addWidget(b)
        v.addStretch(1)
        zoom = QHBoxLayout()
        self.fit_btn = Segmented([("fit", "Fit"), ("actual", "100%")], "fit")
        self.fit_btn.changed.connect(self._fit)
        zoom.addWidget(label("Size", "muted"))
        zoom.addStretch(1)
        zoom.addWidget(self.fit_btn)
        self.zoom_row = QWidget()
        self.zoom_row.setLayout(zoom)
        v.addWidget(self.zoom_row)
        nav = QHBoxLayout()
        prev_b = button("Previous", icon=icons.icon("sort_up", theme.TEXT, 14), tip="Previous item (←)")
        prev_b.clicked.connect(lambda: self.coll.step(-1))
        next_b = button("Next", icon=icons.icon("sort_down", theme.TEXT, 14), tip="Next item (→)")
        next_b.clicked.connect(lambda: self.coll.step(1))
        nav.addWidget(prev_b, 1)
        nav.addWidget(next_b, 1)
        v.addLayout(nav)
        back = button("Back to the list", "ghost", tip="Esc")
        back.clicked.connect(self.coll.leave_full_view)
        v.addWidget(back)
        v.addWidget(label("← → move · Space ticks · 0 fit · 1 actual size · Esc back",
                          "caption", wrap=True))
        side_scroll = QScrollArea()  # a short window scrolls the panel instead of cutting its buttons off
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setFixedWidth(300)
        side_scroll.setWidget(side)
        h.addWidget(side_scroll)
        coll.thumbs.ready.connect(self._thumb_ready)

    def _fit(self, value):
        self.stage.fit = value == "fit"
        self.stage._refresh()

    def set_fit(self, fit):
        self.fit_btn.set_value("fit" if fit else "actual")
        self._fit("fit" if fit else "actual")

    def show_item(self, item, number, total):
        self.item = item
        if item is None:
            self.name.setText("Nothing to show")
            self.position.setText("")
            self.stage.show_message("Nothing here yet.")
            self.stack.setCurrentWidget(self.stage)
            return
        self.name.setText(item["name"])
        self.position.setText(f"{number} of {total}")
        self.tick.setChecked(item["ticked"])
        while self.details.count():
            w = self.details.takeAt(0).widget()
            if w:
                w.deleteLater()
        for row, (k, val) in enumerate(self.coll.details(item)):
            self.details.addWidget(label(k, "caption"), row, 0, Qt.AlignTop)
            self.details.addWidget(label(str(val), "value", wrap=True), row, 1)
        is_video = self.coll.kind == "video"
        self.zoom_row.setVisible(not is_video)
        if is_video and self.player is not None and self.player.ok:
            self.stack.setCurrentWidget(self.player)
            self.player.load(item["path"])
        else:
            self.stack.setCurrentWidget(self.stage)
            self._load_picture(item)

    def _load_picture(self, item):
        if self.coll.kind == "image":
            pm = QPixmap(item["path"])
            if not pm.isNull():
                self.stage.show_image(pm)
                return
        image = self.coll.thumbs.get(item["path"])
        if image is not None:
            self.stage.show_image(QPixmap.fromImage(image))
        else:
            self.stage.show_message("Making a preview…")

    def _thumb_ready(self, path):
        if self.item and self.item["path"] == path and self.isVisible() and self.stack.currentWidget() is self.stage:
            self._load_picture(self.item)

    def refresh_tick(self):
        if self.item:
            self.tick.setChecked(self.item["ticked"])

    def stop(self):
        if self.player is not None:
            self.player.stop()


# ----- the collection -----
class Collection(QWidget):
    """One set of items shown as List, Grid or Gallery, with the folder tree beside it."""
    selection_changed = Signal(object)   # the selected item, or None
    ticks_changed = Signal()
    view_changed = Signal(str)

    def __init__(self, key, columns, kind="video", noun=("video", "videos"), details=None, gallery_actions=(),
                 empty=None, subline=None, folder_tree=True, default_view="list"):
        super().__init__()
        self.key, self.kind, self.noun = key, kind, noun
        self.kind_icon = "silent" if kind == "video" else "image"
        self.details = details or (lambda item: [("Folder", item["root"] + ("/" + item["rel_folder"]
                                                                           if item["rel_folder"] else "")),
                                                 ("Size", fileops.human_size(item["size"]))])
        self.subline = subline or (lambda item: fileops.human_size(item["size"]) if item.get("size") else "")
        self.gallery_actions = list(gallery_actions)
        self.anchor = None
        self.thumbs = thumbs.shared()
        saved = settings.load().get("views", {}).get(key, {})
        self.grid_size = max(GRID_MIN, min(GRID_MAX, int(saved.get("size", 180))))
        self.model = Model(columns)
        self.model.ticks_changed.connect(self._ticks)
        self.proxy = Proxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.layoutChanged.connect(self._count)
        self.proxy.rowsInserted.connect(self._count)
        self.proxy.modelReset.connect(self._count)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.GAP - 2)

        # the summary line: count, sort, size, views
        self.summary = ElidedLabel("")
        self.sort_box = QComboBox()
        for n, col in enumerate(columns):
            self.sort_box.addItem(f"Sort by {col.title.lower()}", n)
        self.sort_box.setToolTip("Sort by")
        self.sort_box.currentIndexChanged.connect(lambda _i: self._sort())
        self.sort_dir = QPushButton()
        self.sort_dir.setProperty("kind", "ghost")
        self.sort_dir.setFixedWidth(30)
        self.sort_dir.setCheckable(True)
        self.sort_dir.setToolTip("Reverse the order")
        self.sort_dir.toggled.connect(lambda _on: self._sort())
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(GRID_MIN, GRID_MAX)
        self.size_slider.setValue(self.grid_size)
        self.size_slider.setFixedWidth(96)
        self.size_slider.setToolTip("Picture size (Ctrl + mouse wheel, or + and −)")
        self.size_slider.valueChanged.connect(self._set_size)
        self.views = Segmented([("list", "List"), ("grid", "Grid"), ("gallery", "Gallery")],
                               saved.get("view", default_view))
        for k, ic in (("list", "list"), ("grid", "grid"), ("gallery", "gallery")):
            self.views.buttons[k].setIcon(icons.icon(ic, theme.SEC, 14))
        self.views.changed.connect(self.set_view)
        bar = QHBoxLayout()
        bar.setSpacing(theme.GAP - 2)
        bar.addWidget(self.summary, 1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(theme.GAP - 2)
        bar.addLayout(self.extra)
        for w in (self.sort_box, self.sort_dir, self.size_slider, self.views):
            bar.addWidget(w)
        outer.addLayout(bar)

        # the views
        self.stack = QStackedWidget()
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setHighlightSections(False)
        hh.setMinimumSectionSize(48)
        for n, col in enumerate(columns):
            if n:
                self.table.setColumnWidth(n, col.width)
        hh.sortIndicatorChanged.connect(self._header_sorted)
        self.table.setItemDelegate(TintDelegate(self.table))
        self.selection = self.table.selectionModel()
        self.stack.addWidget(self.table)
        TickFilter(self, self.table)

        self.grid = QListView()
        self.grid.setObjectName("grid")
        self.grid.setModel(self.proxy)
        self.grid.setSelectionModel(self.selection)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSpacing(2)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setItemDelegate(GridDelegate(self))
        self.grid.setDragEnabled(False)  # icon mode would otherwise let items be dragged around
        self.grid.setAcceptDrops(False)  # folders dropped on the grid go to the screen, which adds them
        self.grid.viewport().installEventFilter(self)
        self.stack.addWidget(self.grid)
        TickFilter(self, self.grid, grid=True)
        self.gallery = Gallery(self)
        self.stack.addWidget(self.gallery)
        icon_name, sentence, btn_text, btn_action = empty or ("folder", "Nothing here yet.", None, None)
        self.empty = EmptyState(icon_name, sentence, btn_text, btn_action)
        self.stack.addWidget(self.empty)
        self.selection.currentRowChanged.connect(self._current)

        if folder_tree:
            self.tree = FolderTree()
            self.tree.picked.connect(self._folder_picked)
            split = QSplitter(Qt.Horizontal)
            split.setChildrenCollapsible(False)
            split.setHandleWidth(theme.GAP)
            self.tree_panel = QWidget()
            tv = QVBoxLayout(self.tree_panel)
            tv.setContentsMargins(0, 0, 0, 0)
            tv.addWidget(self.tree)
            self.tree_panel.setMinimumWidth(160)
            split.addWidget(self.tree_panel)
            split.addWidget(self.stack)
            split.setStretchFactor(0, 0)
            split.setStretchFactor(1, 1)
            split.setSizes([210, 800])
            remember(f"{key}_tree_split", split)
            outer.addWidget(split, 1)
        else:
            self.tree = None
            self.tree_panel = None
            outer.addWidget(self.stack, 1)
        self.roots = []
        self.thumbs.ready.connect(self._thumb_ready)
        theme.on_change(self._recolour)
        self._last_view = self.views.value() if self.views.value() != "gallery" else "list"
        sort_saved = saved.get("sort")
        if sort_saved is not None and 0 <= sort_saved[0] < len(columns):
            self.sort_box.setCurrentIndex(sort_saved[0])
            self.sort_dir.setChecked(bool(sort_saved[1]))
        self._sort()
        self.set_view(self.views.value(), save=False)
        self._count()

    # ----- items -----
    def set_roots(self, roots):
        self.roots = list(roots)
        self._refill_tree()

    def set_items(self, items):
        self.model.set_items(items)
        self._refill_tree()
        self._show_view()

    def add_items(self, items):
        self.model.add(items)
        self._refill_tree()
        self._show_view()

    def items(self):
        return list(self.model.items)

    def find(self, path):
        return self.model.find(path)

    def update(self, path, **fields):
        item = self.model.find(path)
        if item is not None:
            item.update(fields)
            self.model.changed(item)
            if self.gallery.item is item and self.stack.currentWidget() is self.gallery:
                self.gallery.refresh_tick()
        return item

    def remove(self, paths):
        selected = self.selected()
        self.model.remove(paths)
        self._refill_tree()
        if selected and self.model.find(selected["path"]):
            self.select(selected)
        self._show_view()

    def ticked(self):
        return [i for i in self.model.items if i["ticked"]]

    def item_at(self, index):
        """The item itself (not a copy) behind a view's index."""
        if not index.isValid():
            return None
        row = self.proxy.mapToSource(self.proxy.index(index.row(), 0)).row()
        return self.model.items[row] if 0 <= row < len(self.model.items) else None

    def shown(self):
        return [self.item_at(self.proxy.index(r, 0)) for r in range(self.proxy.rowCount())]

    def selected(self):
        index = self.selection.currentIndex()
        return self.item_at(index) if index.isValid() else None

    def targets(self):
        """What actions work on: the ticked items, or the selected one when nothing is ticked."""
        ticked = self.ticked()
        if ticked:
            return ticked
        sel = self.selected()
        return [sel] if sel else []

    def select(self, item):
        row = self.model.rows.get(norm(item["path"]))
        if row is None:
            return
        index = self.proxy.mapFromSource(self.model.index(row, 0))
        if index.isValid():
            self.selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            view = self.table if self.stack.currentWidget() is self.table else self.grid
            view.scrollTo(index)

    # ----- ticking -----
    def toggle(self, item):
        self.model.set_ticked([item], not item["ticked"])
        self.anchor = item

    def tick_range(self, a, b):
        shown = self.shown()
        try:
            i, j = sorted((shown.index(a), shown.index(b)))
        except ValueError:
            return
        self.model.set_ticked(shown[i:j + 1], True)
        self.anchor = b

    def tick_all(self, on=None):
        shown = self.shown()
        if on is None:
            on = not all(i["ticked"] for i in shown)  # Ctrl+A again unticks
        self.model.set_ticked(shown, on)

    def _ticks(self):
        self._count()
        self.gallery.refresh_tick()
        self.grid.viewport().update()
        self.ticks_changed.emit()

    # ----- views -----
    def view(self):
        return self.views.value()

    def set_view(self, view, save=True):
        if view != "gallery":
            self._last_view = view
            self.gallery.stop()
        self.views.set_value(view)
        self.size_slider.setVisible(view == "grid")
        if save:
            self._save_view()
        self._show_view()
        self.view_changed.emit(view)

    def _show_view(self):
        view = self.views.value()
        if not self.model.items:
            self.stack.setCurrentWidget(self.empty)
            self.gallery.stop()
            return
        if view == "gallery":
            self.stack.setCurrentWidget(self.gallery)
            if self.selected() is None and self.proxy.rowCount():
                self.selection.setCurrentIndex(self.proxy.index(0, 0), QItemSelectionModel.ClearAndSelect
                                               | QItemSelectionModel.Rows)
            self._show_gallery_item()
        elif view == "grid":
            self.stack.setCurrentWidget(self.grid)
        else:
            self.stack.setCurrentWidget(self.table)

    def open_gallery(self, index):
        self.selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.set_view("gallery")

    def leave_full_view(self):
        if self.views.value() == "gallery":
            self.set_view(self._last_view)
            return True
        return False

    def _show_gallery_item(self):
        index = self.selection.currentIndex()
        if not index.isValid():
            self.gallery.show_item(None, 0, 0)
            return
        self.gallery.show_item(self.item_at(index), index.row() + 1, self.proxy.rowCount())

    def step(self, delta):
        rows = self.proxy.rowCount()
        if not rows:
            return False
        current = self.selection.currentIndex()
        row = current.row() if current.isValid() else -1
        if delta == float("-inf"):
            row = 0
        elif delta == float("inf"):
            row = rows - 1
        else:
            row = max(0, min(rows - 1, row + int(delta)))
        self.selection.setCurrentIndex(self.proxy.index(row, 0),
                                       QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        return True

    def space(self):
        item = self.selected()
        if item is None:
            return False
        self.toggle(item)
        return True

    def zoom(self, step):
        if self.views.value() == "grid":
            self.size_slider.setValue(self.grid_size + 20 * step)
            return True
        if self.views.value() == "gallery":
            self.gallery.set_fit(step < 0)
            return True
        return False

    def fit(self, actual):
        if self.views.value() == "gallery":
            self.gallery.set_fit(not actual)
            return True
        return False

    def _set_size(self, value):
        self.grid_size = value
        self.grid.setGridSize(QSize(value + 12, int(value * 0.75) + 12 + 40))
        self.grid.doItemsLayout()
        self._save_view()

    def eventFilter(self, obj, event):
        if obj is self.grid.viewport() and event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return False

    def _save_view(self):
        views = dict(settings.load().get("views", {}))
        views[self.key] = {"view": self.views.value() if self.views.value() != "gallery" else self._last_view,
                           "size": self.grid_size,
                           "sort": [self.sort_box.currentIndex(), int(self.sort_dir.isChecked())]}
        settings.save({"views": views})

    # ----- sorting -----
    def _sort(self):
        col = self.sort_box.currentData() or 0
        order = Qt.DescendingOrder if self.sort_dir.isChecked() else Qt.AscendingOrder
        self.sort_dir.setIcon(icons.icon("sort_down" if self.sort_dir.isChecked() else "sort_up", theme.SEC, 14))
        hh = self.table.horizontalHeader()
        hh.blockSignals(True)
        hh.setSortIndicator(col, order)
        hh.blockSignals(False)
        self.proxy.sort(col, order)
        if hasattr(self, "grid"):
            self._save_view()

    def _header_sorted(self, col, order):
        self.sort_box.blockSignals(True)
        self.sort_box.setCurrentIndex(col)
        self.sort_box.blockSignals(False)
        self.sort_dir.blockSignals(True)
        self.sort_dir.setChecked(order == Qt.DescendingOrder)
        self.sort_dir.blockSignals(False)
        self._sort()

    # ----- folders -----
    def _refill_tree(self):
        if self.tree is not None:
            self.tree.fill(self.roots, self.model.items)
        self._count()

    def _folder_picked(self, folder):
        self.proxy.set_folder(folder)
        self._count()
        if self.views.value() == "gallery":
            self._show_gallery_item()

    # ----- signals -----
    def _current(self, current, _previous):
        item = self.item_at(current) if current.isValid() else None
        if item is not None and self.anchor is None:
            self.anchor = item
        if self.views.value() == "gallery":
            self._show_gallery_item()
        self.selection_changed.emit(item)

    def _thumb_ready(self, path):
        if self.stack.currentWidget() is self.grid:
            self.grid.viewport().update()

    def _count(self):
        total = len(self.model.items)
        shown = self.proxy.rowCount()
        ticked = len(self.ticked())
        one, many = self.noun
        text = f"{total} {one if total == 1 else many}"
        if shown != total:
            text = f"{shown} of {total} {many} shown"
        if ticked:
            hidden = ticked - sum(1 for i in self.shown() if i["ticked"])
            text += f" · {ticked} ticked" + (f" ({hidden} not shown)" if hidden else "")
        self.summary.setText(text if total else "")

    def _recolour(self):
        for k, ic in (("list", "list"), ("grid", "grid"), ("gallery", "gallery")):
            self.views.buttons[k].setIcon(icons.icon(ic, theme.SEC, 14))
        self.sort_dir.setIcon(icons.icon("sort_down" if self.sort_dir.isChecked() else "sort_up", theme.SEC, 14))
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        if self.tree is not None:
            self.tree.fill(self.roots, self.model.items)
        self.grid.viewport().update()

    def set_empty(self, sentence, action_text=None):
        self.empty.set_text(sentence, action_text)

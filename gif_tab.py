"""GIF maker page: pick videos, optionally set a timeframe for each, then convert them."""
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QSizePolicy, QSplitter, QTreeWidgetItem, QVBoxLayout, QWidget)

import gif_maker
import icons
import theme
from media_utils import find_videos, probe_duration
from widgets import Page, button, card, folder_row, label, line_edit, make_tree, muted, remember

MIN_CLIP = 0.1  # shortest allowed timeframe, in seconds
ITEM_PATH = Qt.UserRole


def fmt_time(seconds):
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def parse_time(text):
    """Accepts seconds ("83.5") or m:ss.s ("1:23.5")."""
    text = text.strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return float(minutes) * 60 + float(seconds)
    return float(text)


def to_pixmap(pil_image):
    img = pil_image.convert("RGBA")
    qimg = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, 4 * img.width,
                  QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


class Timeline(QWidget):
    """A bar showing the whole video, with the GIF's start and end handles on it. Stretches to the width."""
    changed = Signal(float, float)    # while a handle is dragged
    released = Signal(float, float)   # when the handle is let go

    def __init__(self):
        super().__init__()
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self._drag = None
        self.setMinimumHeight(theme.px(72))
        self.setMinimumWidth(theme.px(200))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_range(self, duration, start, end):
        self.duration, self.start, self.end = duration, start, end
        self.update()

    def _x(self, t):
        pad = theme.px(14)
        span = max(1, self.width() - 2 * pad)
        return pad + (t / self.duration) * span if self.duration else pad

    def _t(self, x):
        pad = theme.px(14)
        span = max(1, self.width() - 2 * pad)
        return min(max((x - pad) / span * self.duration, 0.0), self.duration)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = theme.px(14)
        caption_h = theme.text_px("caption") + theme.px(10)
        top = theme.px(12)
        bottom = h - caption_h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawRoundedRect(QRectF(pad, top, w - 2 * pad, bottom - top), theme.px(6), theme.px(6))
        if self.duration:
            xs, xe = self._x(self.start), self._x(self.end)
            p.setBrush(QColor(theme.GREEN))
            p.drawRoundedRect(QRectF(xs, top, max(1.0, xe - xs), bottom - top), theme.px(6), theme.px(6))
            p.setPen(QPen(QColor("#ffffff"), max(2, theme.px(3))))
            for x in (xs, xe):
                p.drawLine(int(x), top - theme.px(5), int(x), bottom + theme.px(5))
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font("caption"))
        caption = QRectF(pad, bottom + theme.px(4), w - 2 * pad, caption_h)
        p.drawText(caption, Qt.AlignLeft | Qt.AlignVCenter, "0:00.0")
        p.drawText(caption, Qt.AlignRight | Qt.AlignVCenter, fmt_time(self.duration))
        p.end()

    def mousePressEvent(self, event):
        if not self.duration:
            return
        xs, xe = self._x(self.start), self._x(self.end)
        x = event.position().x()
        self._drag = "start" if abs(x - xs) <= abs(x - xe) else "end"
        self._move(x)

    def mouseMoveEvent(self, event):
        if self._drag:
            self._move(event.position().x())

    def mouseReleaseEvent(self, _event):
        if self._drag:
            self._drag = None
            self.released.emit(self.start, self.end)

    def _move(self, x):
        t = self._t(x)
        if self._drag == "start":
            self.start = max(0.0, min(t, self.end - MIN_CLIP))
        else:
            self.end = min(self.duration, max(t, self.start + MIN_CLIP))
        self.update()
        self.changed.emit(self.start, self.end)


class VideoItem(QTreeWidgetItem):
    """One row of the video list. Remembers what the sorting needs, so any column can be sorted."""

    def __init__(self, path, folder):
        self.name = str(path.relative_to(folder))
        super().__init__([self.name, "", "whole video"])
        self.path = str(path)
        self.seconds = None   # length of the video, once read
        self.clip = None      # (start, end) when a timeframe is set
        self.setData(0, ITEM_PATH, self.path)

    def _sort_key(self, column):
        if column == 0:
            return self.name.casefold()
        if column == 1:
            return self.seconds if self.seconds is not None else -1.0
        return (0, 0.0) if self.clip is None else (1, self.clip[0])  # whole video first, then clips

    def __lt__(self, other):
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        return self._sort_key(column) < other._sort_key(column)


class Preview(QLabel):
    """Shows a frame scaled to fit the box, and rescales it when the box is resized."""

    def __init__(self):
        super().__init__("No video selected")
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("role", "muted")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._source = None

    def minimumSizeHint(self):
        return QSize(1, 1)  # the picture must never push the layout bigger

    def sizeHint(self):
        return QSize(theme.px(200), theme.px(150))

    def show_frame(self, pixmap):
        self._source = pixmap
        self._refresh()

    def show_message(self, text):
        self._source = None
        self.clear()
        self.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if self._source is None:
            return
        room = self.size() - QSize(theme.px(12), theme.px(12))
        self.setPixmap(self._source.scaled(max(1, room.width()), max(1, room.height()),
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))


class GifTab(Page):
    title = "GIF maker"
    subtitle = "Turn videos into GIFs. Pick a timeframe for any video, or leave it to convert the whole thing."

    def build(self):
        self.folder = line_edit(placeholder="Choose a folder")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.fps = line_edit("12", width=70)
        self.width_px = line_edit("480", width=80)
        self.quality = QComboBox()
        self.quality.addItems(list(gif_maker.QUALITY_PRESETS))
        self.out_dir = line_edit(placeholder="Empty = beside each video")
        self.durations = {}   # video path -> seconds
        self.ranges = {}      # video path -> (start, end), only once a timeframe is set
        self.items = {}       # video path -> list row
        self.current = None   # path shown in the timeframe editor
        self._preview_id = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._request_previews)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        left.setMinimumWidth(theme.px(440))
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, theme.px(8), 0)
        left_col.setSpacing(theme.px(12))
        right = QWidget()
        right.setMinimumWidth(theme.px(420))
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(theme.px(8), 0, 0, 0)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        remember("gif_split", split)  # the panels share the width evenly unless you have dragged them
        self.body.addWidget(split, 1)

        # Left: settings, actions, then the video list (which takes the remaining height)
        setup = card()
        grid = QGridLayout(setup)
        grid.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        grid.setHorizontalSpacing(theme.px(10))
        grid.setVerticalSpacing(theme.px(10))
        grid.setColumnStretch(1, 1)
        folder_row(grid, 0, "Video folder", self.folder, "Choose the video folder")
        load_row = QHBoxLayout()
        load_row.addWidget(self.recursive)
        load_row.addSpacing(theme.px(16))
        load_btn = button("Load videos", "primary", icons.icon("gif", theme.ON_GREEN, 18))
        load_btn.clicked.connect(self.load_videos)
        load_row.addWidget(load_btn)
        load_row.addStretch(1)
        grid.addLayout(load_row, 1, 0, 1, 3)
        grid.addWidget(muted("FPS"), 2, 0)
        grid.addWidget(self.fps, 2, 1, Qt.AlignLeft)
        grid.addWidget(muted("Width (px)"), 3, 0)
        grid.addWidget(self.width_px, 3, 1, Qt.AlignLeft)
        grid.addWidget(muted("Quality"), 4, 0)
        grid.addWidget(self.quality, 4, 1, Qt.AlignLeft)
        folder_row(grid, 5, "Save GIFs to", self.out_dir, "Save GIFs to...")
        grid.addWidget(label("Higher quality = better colours, bigger file, slower", "caption", wrap=True), 6, 0, 1, 3)
        left_col.addWidget(setup)

        actions = QGridLayout()
        actions.setHorizontalSpacing(theme.px(8))
        actions.setVerticalSpacing(theme.px(8))
        actions.addWidget(self._button("Select all", self.select_all), 0, 0)
        actions.addWidget(self._button("Clear timeframes", self.clear_selected_ranges), 0, 1)
        actions.addWidget(self._button("Convert selected", lambda: self.convert(True), "primary",
                                       icons.icon("gif", theme.ON_GREEN, 18)), 1, 0)
        actions.addWidget(self._button("Convert all", lambda: self.convert(False), "primary"), 1, 1)
        left_col.addLayout(actions)

        list_card = card()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(theme.px(8), theme.px(8), theme.px(8), theme.px(8))
        self.tree = make_tree(("File", "Length", "Timeframe"), (200, 80, 130))
        self.tree.setSortingEnabled(True)  # click a heading to sort by it, click again to reverse
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        remember("gif_tree", self.tree, header=True)
        self.tree.currentItemChanged.connect(self._on_current)
        list_layout.addWidget(self.tree)
        left_col.addWidget(list_card, 1)

        # Right: the timeframe editor, whose previews take the remaining height
        editor = card()
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(16))
        ev.setSpacing(theme.px(10))
        head = QHBoxLayout()
        head.addWidget(label("Timeframe", "heading"))
        head.addWidget(muted("Click a video in the list to set its clip", wrap=True))
        head.addStretch(1)
        ev.addLayout(head)

        self.timeline = Timeline()
        self.timeline.changed.connect(self._on_drag)
        self.timeline.released.connect(self._on_release)
        ev.addWidget(self.timeline)

        controls = QGridLayout()
        controls.setHorizontalSpacing(theme.px(8))
        controls.setVerticalSpacing(theme.px(8))
        self.start_edit = line_edit(width=96)
        self.end_edit = line_edit(width=96)
        self.start_edit.returnPressed.connect(self._apply_entries)
        self.end_edit.returnPressed.connect(self._apply_entries)
        controls.addWidget(muted("Start"), 0, 0)
        controls.addWidget(self.start_edit, 0, 1)
        controls.addWidget(muted("End"), 0, 2)
        controls.addWidget(self.end_edit, 0, 3)
        apply_btn = button("Apply")
        apply_btn.clicked.connect(self._apply_entries)
        whole_btn = button("Whole video")
        whole_btn.clicked.connect(self._reset_range)
        controls.addWidget(apply_btn, 1, 0, 1, 2)
        controls.addWidget(whole_btn, 1, 2, 1, 2)
        self.length_label = label("", "heading")
        controls.addWidget(self.length_label, 2, 0, 1, 4)
        controls.setColumnStretch(4, 1)
        ev.addLayout(controls)

        previews = QGridLayout()
        previews.setHorizontalSpacing(theme.px(12))
        previews.setVerticalSpacing(0)
        self.start_view = Preview()
        self.end_view = Preview()
        previews.addWidget(self._preview_box("Clip starts at", self.start_view), 0, 0)
        previews.addWidget(self._preview_box("Clip ends at", self.end_view), 0, 1)
        ev.addLayout(previews, 1)
        right_col.addWidget(editor, 1)

    def _button(self, text, command, kind="secondary", icon=None):
        b = button(text, kind, icon)
        b.clicked.connect(command)
        return b

    def _preview_box(self, caption, view):
        box = card()
        box.setObjectName("preview")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(theme.px(14), theme.px(10), theme.px(14), theme.px(14))
        layout.addWidget(label(caption, "caption"))
        layout.addWidget(view, 1)
        return box

    # ---------- loading ----------
    def load_videos(self):
        folder = self.folder.text().strip()
        if not Path(folder).is_dir():
            QMessageBox.critical(self, "Folder not found", "Choose a valid video folder.")
            return
        videos = find_videos(folder, self.recursive.isChecked())
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.items = {}
        self.durations = {}
        self.ranges = {}
        self.current = None
        for path in videos:
            row = VideoItem(path, Path(folder))
            self.tree.addTopLevelItem(row)
            self.items[str(path)] = row
        self.tree.setSortingEnabled(True)
        self.app.log(f"Loaded {len(videos)} video(s). Reading their lengths...")
        self._clear_editor()
        self._read_all_lengths([str(p) for p in videos])

    def _read_all_lengths(self, paths):
        """Read every video's length in the background, so the Length column fills in by itself."""
        def worker():
            for iid in paths:
                seconds = probe_duration(iid)
                self.app.on_main(lambda iid=iid, seconds=seconds: self._set_duration(iid, seconds))
            self.app.on_main(lambda: self.app.log("Finished reading video lengths."))

        threading.Thread(target=worker, daemon=True).start()

    def _set_duration(self, iid, seconds):
        if iid not in self.items:
            return  # the list was reloaded since
        if seconds is None:
            self.app.log(f"Could not read the length of {Path(iid).name}")
            return
        self.durations[iid] = seconds
        row = self.items[iid]
        row.seconds = seconds
        row.setText(1, fmt_time(seconds))
        self._resort()

    def _resort(self):
        header = self.tree.header()
        self.tree.sortItems(header.sortIndicatorSection(), header.sortIndicatorOrder())

    def select_all(self):
        self.tree.selectAll()

    # ---------- selecting a video and editing its timeframe ----------
    def _on_current(self, current, _previous):
        if current is None:
            return
        iid = current.data(0, ITEM_PATH)
        if iid == self.current:
            return
        self.current = iid
        self._ensure_duration(iid, lambda: self._show_editor(iid))

    def _ensure_duration(self, iid, then):
        if iid in self.durations:
            then()
            return

        def worker():
            seconds = probe_duration(iid)

            def done():
                self._set_duration(iid, seconds)
                if iid in self.durations:
                    then()
            self.app.on_main(done)

        threading.Thread(target=worker, daemon=True).start()

    def _show_editor(self, iid):
        if self.current != iid:  # the user has moved on to another video
            return
        duration = self.durations[iid]
        start, end = self.ranges.get(iid, (0.0, duration))
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._request_previews()

    def _clear_editor(self):
        self.current = None
        self.timeline.set_range(0.0, 0.0, 0.0)
        self.start_edit.setText("")
        self.end_edit.setText("")
        self.length_label.setText("")
        self.start_view.show_message("No video selected")
        self.end_view.show_message("No video selected")

    def _update_labels(self, start, end):
        self.start_edit.setText(fmt_time(start))
        self.end_edit.setText(fmt_time(end))
        self.length_label.setText(f"Length: {end - start:.1f}s")

    def _store(self, start, end, resort=True):
        """Remember the timeframe for the current video (or clear it if it covers the whole video)."""
        iid = self.current
        if iid is None or iid not in self.items:
            return
        duration = self.durations[iid]
        row = self.items[iid]
        if start <= 0.05 and end >= duration - 0.05:
            self.ranges.pop(iid, None)
            row.clip = None
            row.setText(2, "whole video")
        else:
            self.ranges[iid] = (start, end)
            row.clip = (start, end)
            row.setText(2, f"{fmt_time(start)} to {fmt_time(end)}")
        if resort:
            self._resort()

    def _on_drag(self, start, end):
        self._update_labels(start, end)
        self._store(start, end, resort=False)  # re-sort once the handle is let go, not on every move
        self._preview_timer.start()

    def _on_release(self, start, end):
        self._store(start, end)  # sorts once the handle is let go
        self._request_previews()

    def _apply_entries(self):
        iid = self.current
        if not iid:
            return
        duration = self.durations[iid]
        try:
            start = parse_time(self.start_edit.text())
            end = parse_time(self.end_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid time", "Enter times like 12.5 or 1:23.5.")
            return
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start < MIN_CLIP:
            QMessageBox.critical(self, "Invalid timeframe", f"The end must be at least {MIN_CLIP} s after the start.")
            return
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._store(start, end)
        self._request_previews()

    def _reset_range(self):
        iid = self.current
        if not iid:
            return
        self.ranges.pop(iid, None)
        self.items[iid].clip = None
        self.items[iid].setText(2, "whole video")
        self._resort()
        self._show_editor(iid)

    def clear_selected_ranges(self):
        selected = self.tree.selectedItems()
        for row in selected:
            iid = row.data(0, ITEM_PATH)
            self.ranges.pop(iid, None)
            row.clip = None
            row.setText(2, "whole video")
        self._resort()
        if self.current and any(r.data(0, ITEM_PATH) == self.current for r in selected):
            self._show_editor(self.current)

    # ---------- start and end frame previews ----------
    def _request_previews(self):
        iid = self.current
        if not iid:
            return
        start, end = self.timeline.start, self.timeline.end
        self._preview_id += 1
        token = self._preview_id

        def worker():
            first = gif_maker.extract_frame(iid, start)
            last = gif_maker.extract_frame(iid, max(end - 0.05, start))
            self.app.on_main(lambda: self._show_previews(token, first, last))

        threading.Thread(target=worker, daemon=True).start()

    def _show_previews(self, token, first, last):
        if token != self._preview_id:  # a newer preview has been requested since
            return
        for view, img in ((self.start_view, first), (self.end_view, last)):
            if img is None:
                view.show_message("Could not read this frame")
            else:
                view.show_frame(to_pixmap(img))

    # ---------- converting ----------
    def convert(self, selected_only):
        rows = self.tree.selectedItems() if selected_only else [
            self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        if not rows:
            QMessageBox.information(self, "Nothing selected", "Select one or more videos first, or use Convert all.")
            return
        try:
            fps = int(self.fps.text())
            width = int(self.width_px.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid settings", "FPS and width must be whole numbers.")
            return
        if not (1 <= fps <= 60) or not (64 <= width <= 1920):
            QMessageBox.critical(self, "Invalid settings", "FPS must be 1 to 60, and width 64 to 1920 pixels.")
            return
        out_dir = self.out_dir.text().strip() or None
        jobs = []
        for row in rows:
            iid = row.data(0, ITEM_PATH)
            if iid in self.ranges:
                start, end = self.ranges[iid]
                jobs.append((Path(iid), start, end))
            else:
                jobs.append((Path(iid), 0.0, None))
        self.app.run_background(gif_maker.convert_batch, jobs, fps, width, self.quality.currentText(), out_dir)

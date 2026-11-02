"""Duplicate videos page: a front end for the vdf-cli engine (see duplicates_engine.py).

Three columns: the setup (left), the list of groups and their files (middle), and the copies of the selected
group side by side, which zoom and open when clicked (right)."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QListWidget, QMessageBox, QScrollArea, QSlider, QSpinBox, QSplitter, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

import duplicates_engine as de
import icons
import settings
import theme
from widgets import (ElidedLabel, Page, add_folder, button, empty_state, field_label, label, line_edit, muted,
                     remember, results_panel, tool_row, toolbar)

LEFT_W = 290          # the options column (including room for its scroll bar)
MIDDLE_MIN_W = 372    # the groups list
COMPARE_MIN_W = 262   # the comparison
CARD_W = 250          # a copy card at 100% size

ROW_PATH = Qt.UserRole
ROW_GROUP = Qt.UserRole + 1
VIDEO_FILTER = "Videos (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.3gp);;All files (*.*)"
ZOOM_MIN, ZOOM_MAX = 0.5, 2.0

EXPLAIN_EXACT = ("Exact and near duplicates are always on. Exact copies are the same video; near duplicates are "
                 "re-encodes, different resolutions or bitrates. Lower the similarity to catch more, at the cost "
                 "of false matches.")
EXPLAIN_AUDIO = ("Finds a shorter clip cut from a longer video by comparing the sound. Good for trimmed clips that "
                 "kept their audio. Videos with no audio track are skipped in this mode.")
EXPLAIN_VISUAL = ("Finds clips cut from a longer video by comparing the pictures using AI. Works without audio. "
                  "The first time it is used, about 100 MB of AI components are downloaded.")


def _to_qimage(pil_image):
    img = pil_image.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, 4 * img.width,
                  QImage.Format_RGBA8888).copy()


def _open_path(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - the user's chosen file, opened with its default program
    else:
        subprocess.Popen(["xdg-open", path])


def _show_in_explorer(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


def _size_text(n):
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


class NoWheelSlider(QSlider):
    """Scrolling over a slider scrolls the page around it, instead of moving the slider."""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpin(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelCombo(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class CopyCard(QFrame):
    """One copy in the comparison: a preview, the name and the details that tell the copies apart.
    Click it to open the video; right-click for more. Everything scales with the size slider."""
    clicked = Signal(str)
    context_requested = Signal(str, object)

    def __init__(self, item, qimg):
        super().__init__()
        self.setObjectName("copy")
        self.path = item["path"]
        self.pixmap = QPixmap.fromImage(qimg) if qimg is not None else None
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{item['path']}\nClick to open. Right-click for more.")

        v = QVBoxLayout(self)
        self.v = v
        self.thumb = QLabel()
        self.thumb.setObjectName("thumb")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setProperty("role", "empty")
        v.addWidget(self.thumb)

        self.title = label(item["name"], "heading", wrap=True)
        v.addWidget(self.title)
        self.folder = ElidedLabel(item["folder"], "caption")
        v.addWidget(self.folder)
        tags = [text for text, on in (("Best copy", item["best"]), ("Picked file", item.get("picked"))) if on]
        self.badge = label("   ".join(tags), "badge") if tags else None
        if self.badge:
            v.addWidget(self.badge)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 2, 0, 0)
        for row, (key, value) in enumerate(self._details(item)):
            k = label(key, "caption")
            val = label(value, "value", wrap=True)
            self.grid.addWidget(k, row, 0, Qt.AlignLeft | Qt.AlignTop)
            self.grid.addWidget(val, row, 1)  # fills the column, so long values wrap instead of clipping
        self.grid.setColumnStretch(1, 1)
        v.addLayout(self.grid)
        v.addStretch(1)
        self.set_zoom(1.0)

    def _details(self, item):
        rows = [
            ("Match", de.MATCH_LABELS.get(item["match"], item["match"])),
            ("Similarity", f"{item['similarity']:.1f}%"),
            ("Resolution", item["resolution"] or "unknown"),
            ("Size", _size_text(item["size"])),
            ("Duration", de.format_seconds(item["duration"])),
            ("Bitrate", f"{item['bitrate']:.0f} kb/s" if item["bitrate"] else "unknown"),
        ]
        if item["offset"]:
            rows.append(("Starts at", f"{de.format_seconds(item['offset'])} in the longer video"))
        return rows

    def set_zoom(self, zoom):
        width = int(CARD_W * zoom)
        pad = max(6, int(10 * zoom))
        self.setFixedWidth(width)
        inner = width - 2 * pad - 2
        height = int(inner * 9 / 16)
        self.thumb.setFixedSize(inner, height)
        if self.pixmap is not None:
            self.thumb.setPixmap(self.pixmap.scaled(inner, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText("No preview")
        self.v.setContentsMargins(pad, pad, pad, pad)
        self.v.setSpacing(max(2, int(4 * zoom)))
        self.grid.setHorizontalSpacing(max(6, int(10 * zoom)))
        self.grid.setVerticalSpacing(max(1, int(2 * zoom)))
        body = max(9, round(theme.text_px("body") * zoom))
        small = max(9, round(theme.text_px("caption") * zoom))
        self.setStyleSheet(
            f"QLabel {{ font-size: {small}px; }}"
            f"QLabel[role='heading'] {{ font-size: {body}px; }}"
            f"QLabel[role='value'] {{ color: {theme.TEXT}; }}"
            f"QLabel#thumb {{ background: {theme.FIELD}; border-radius: {theme.R_CONTROL}px; }}")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.context_requested.emit(self.path, event.globalPos())


class DuplicatesPage(Page):
    title = "Duplicate videos"
    subtitle = ("Find copies of a video, including smaller re-encodes and trimmed clips. Removed copies go to the "
                "Recycle Bin, never permanently deleted, and every removal is logged.")

    def build(self):
        self.groups = []
        self.by_key = {}
        self.state = None
        self.running = False
        self.thumbs = {}
        self.thumbs_busy = set()
        self.cards = []
        saved = settings.load()
        opts = saved.get("dup_options", {})
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, float(saved.get("dup_zoom", 1.0))))

        # ----- what to search -----
        self.mode = NoWheelCombo()
        self.mode.addItem("Find duplicates in a folder", "folder")
        self.mode.addItem("Check videos against a library", "library")
        self.mode.setCurrentIndex(0 if opts.get("mode", "folder") == "folder" else 1)
        self.mode.currentIndexChanged.connect(self._show_mode)
        self.mode.setFixedWidth(250)

        self.folder = line_edit(saved.get("dup_last_folder", ""), placeholder="Choose the folder to search")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(opts.get("recursive", True))
        self.library = line_edit(saved.get("dup_last_library", ""), placeholder="Choose the library folder")
        self.files = QListWidget()
        self.files.setSelectionMode(QListWidget.ExtendedSelection)
        for path in saved.get("dup_last_files", []):
            if Path(path).exists():
                self.files.addItem(path)

        self.panel_a = QWidget()
        a = tool_row()
        self.panel_a.setLayout(a)
        add_folder(a, "Folder", self.folder, "Choose the folder to search")
        a.addWidget(self.recursive)
        self.panel_b = QWidget()
        b = tool_row()
        self.panel_b.setLayout(b)
        add_folder(b, "Library", self.library, "Choose the library folder to check against")
        add = button("Add videos...")
        add.setToolTip("Choose the videos to check against the library")
        add.clicked.connect(self._add_files)
        b.addWidget(add)

        self.scan_btn = button("Scan", "primary", icons.icon("search", theme.ON_ACCENT, 16))
        self.scan_btn.clicked.connect(self._scan)
        self.cancel_btn = button("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        bar, rows = toolbar()
        top = tool_row()
        top.addWidget(field_label("Mode"))
        top.addWidget(self.mode)
        top.addStretch(1)
        top.addWidget(self.cancel_btn)
        top.addWidget(self.scan_btn)
        rows.addLayout(top)
        what = tool_row()
        what.addWidget(self.panel_a, 1)
        what.addWidget(self.panel_b, 1)
        rows.addLayout(what)
        self.body.addWidget(bar)

        # ----- left column: matching options and the engine -----
        self.percent = NoWheelSlider(Qt.Horizontal)
        self.percent.setRange(50, 100)
        self.percent.setValue(int(opts.get("percent", 95)))
        self.percent.setToolTip(EXPLAIN_EXACT)
        self.percent_label = label("", "muted")
        self.percent_label.setFixedWidth(36)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent.valueChanged.connect(lambda v: self.percent_label.setText(f"{v}%"))
        self.percent_label.setText(f"{self.percent.value()}%")

        self.audio = QCheckBox("Partial clips by audio")
        self.audio.setChecked(opts.get("audio", False))
        self.audio.setToolTip(EXPLAIN_AUDIO)
        self.audio_ratio = self._percent_spin(opts.get("audio_ratio", 10), 1, 100)
        self.audio_ratio.setToolTip("The shortest clip to look for, as a share of the longer video")
        self.audio_sim = self._percent_spin(opts.get("audio_similarity", 80), 1, 100)
        self.audio_sim.setToolTip("How closely the sound must match")
        self.visual = QCheckBox("Partial clips by visual AI")
        self.visual.setChecked(opts.get("visual", False))
        self.visual.setToolTip(EXPLAIN_VISUAL)
        self.visual_hit = self._percent_spin(opts.get("visual_hit", 89), 70, 99)
        self.visual_hit.setToolTip("How closely each frame must match")

        options, ov = results_panel()
        ov.setSpacing(6)
        ov.addWidget(label("Matching", "heading"))
        sim = tool_row()
        sim.addWidget(muted("Similarity"))
        sim.addWidget(self.percent, 1)
        sim.addWidget(self.percent_label)
        ov.addLayout(sim)
        ov.addWidget(label("Exact and near copies are always found. Lower = more matches, more mistakes.",
                           "caption", wrap=True))
        ov.addSpacing(4)
        ov.addWidget(self.audio)
        ov.addWidget(self._indented("Shortest clip", self.audio_ratio))
        ov.addWidget(self._indented("Sound match", self.audio_sim))
        ov.addSpacing(4)
        ov.addWidget(self.visual)
        ov.addWidget(self._indented("Frame match", self.visual_hit))
        ov.addWidget(label("Hover an option to see what it does. Partial clips are off by default; "
                           "visual AI downloads about 100 MB the first time.", "caption", wrap=True))

        self.engine_label = label("", "muted", wrap=True)
        self.ffmpeg_label = label("", "muted", wrap=True)
        self.install_btn = button("Install engine")
        self.install_btn.clicked.connect(self._install_engine)
        self.update_btn = button("Check for update")
        self.update_btn.clicked.connect(self._check_update)
        self.ffmpeg_btn = button("Download FFmpeg")
        self.ffmpeg_btn.clicked.connect(self._install_ffmpeg)
        engine, ev = results_panel()
        ev.setSpacing(6)
        ev.addWidget(label("Engine", "heading"))
        ev.addWidget(self.engine_label)
        eng_row = tool_row()
        eng_row.setSpacing(6)
        eng_row.addWidget(self.install_btn, 1)
        eng_row.addWidget(self.update_btn, 1)
        ev.addLayout(eng_row)
        ev.addWidget(self.ffmpeg_label)
        ev.addWidget(self.ffmpeg_btn)
        ev.addWidget(label("vdf-cli (0x90d/videoduplicatefinder) is downloaded into the app data folder when you "
                           "install it. It is not part of this app.", "caption", wrap=True))

        self.files_card, fv = results_panel()
        files_head = tool_row()
        files_head.addWidget(label("Videos to check", "heading"), 1)
        remove = button("Remove")
        remove.clicked.connect(self._remove_files)
        files_head.addWidget(remove)
        fv.addLayout(files_head)
        self.files.setMinimumHeight(96)
        fv.addWidget(self.files, 1)

        left_host = QWidget()
        self.left = QVBoxLayout(left_host)
        self.left.setContentsMargins(0, 0, 11, 0)  # the scroll bar sits in this margin, never over the options
        self.left.setSpacing(theme.GAP)
        self.left.addWidget(self.files_card)
        self.left.addWidget(options)
        self.left.addWidget(engine)
        self.left.addStretch(1)
        left_scroll = QScrollArea()  # scrolls up and down when the window is short, never sideways
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_host)
        left_scroll.setFixedWidth(LEFT_W)
        self.left_scroll = left_scroll
        self._show_mode(self.mode.currentIndex())

        # ----- middle column: groups and their files -----
        self.filter = NoWheelCombo()
        for text, value in (("All match types", None), ("Exact", "exact"), ("Near", "near"),
                            ("Partial clip (audio)", "partial_audio"),
                            ("Partial clip (visual AI)", "partial_visual")):
            self.filter.addItem(text, value)
        self.filter.currentIndexChanged.connect(lambda _i: self._render())
        self.filter.setToolTip("Show only groups with this kind of match")
        self.sort = NoWheelCombo()
        self.sort.addItem("Largest first", "size")
        self.sort.addItem("Most similar", "similarity")
        self.sort.currentIndexChanged.connect(lambda _i: self._render())
        self.sort.setToolTip("Sort the groups")
        for box in (self.filter, self.sort):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(10)
        self.summary = ElidedLabel("No scan yet.")

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Groups"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(16)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda _item, _c: self._open_selected())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        remember("dup_tree", self.tree, header=True)

        self.btn_keep = button("Keep", "primary")
        self.btn_keep.setToolTip("Keep the selected copy (or the best copy) and send the others to the Recycle Bin")
        self.btn_keep.clicked.connect(self._keep_selected)
        self.btn_delete = button("Delete", "danger")
        self.btn_delete.setToolTip("Send the selected files to the Recycle Bin")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_move = button("Move")
        self.btn_move.setToolTip("Move or copy the selected groups and files to a folder you choose")
        self.btn_move.clicked.connect(self._move_selected)
        self.btn_ignore = button("Ignore")
        self.btn_ignore.setToolTip("Hide this group now and in future scans")
        self.btn_ignore.clicked.connect(self._ignore_group)
        more = QToolButton()
        more.setText("More")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more_menu = QMenu(more)
        self.btn_open = more_menu.addAction("Open video", self._open_selected)
        self.btn_show = more_menu.addAction("Show in Explorer", self._show_selected)
        self.btn_offset = more_menu.addAction("Open clip (offset in the log)", self._open_offset)
        more.setMenu(more_menu)

        middle, mv = results_panel()
        middle.setMinimumWidth(MIDDLE_MIN_W)
        top = tool_row()
        top.setSpacing(6)
        top.addWidget(self.filter, 1)
        top.addWidget(self.sort, 1)
        mv.addLayout(top)
        mv.addWidget(self.summary)
        mv.addWidget(self.tree, 1)
        acts = tool_row()
        acts.setSpacing(6)
        for widget in (self.btn_keep, self.btn_delete, self.btn_move, self.btn_ignore):
            acts.addWidget(widget)
        acts.addStretch(1)
        acts.addWidget(more)
        for widget in (self.btn_keep, self.btn_delete, self.btn_move, self.btn_ignore, more):
            widget.setMinimumWidth(widget.sizeHint().width())  # buttons never squeeze their text
        mv.addLayout(acts)

        # ----- right column: the copies side by side, with zoom -----
        self.compare_host = QWidget()
        self.compare_row = QHBoxLayout(self.compare_host)
        self.compare_row.setContentsMargins(0, 0, 0, 0)
        self.compare_row.setSpacing(theme.GAP)
        self.compare_scroll = QScrollArea()
        self.compare_scroll.setWidgetResizable(True)
        self.compare_scroll.setFrameShape(QFrame.NoFrame)
        self.compare_scroll.setWidget(self.compare_host)
        self.compare_scroll.viewport().installEventFilter(self)  # Ctrl + wheel zooms the cards

        self.zoom_slider = NoWheelSlider(Qt.Horizontal)
        self.zoom_slider.setRange(int(ZOOM_MIN * 100), int(ZOOM_MAX * 100))
        self.zoom_slider.setValue(round(self.zoom * 100))
        self.zoom_slider.valueChanged.connect(lambda v: self._set_zoom(v / 100))
        self.zoom_slider.setFixedWidth(90)
        self.zoom_slider.setToolTip("Card size (Ctrl + mouse wheel over the cards also works)")
        self.zoom_label = label("", "muted")
        self.zoom_label.setFixedWidth(40)
        self.zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        compare, cv = results_panel()
        compare.setMinimumWidth(COMPARE_MIN_W)
        head = tool_row()
        head.addWidget(label("Compare copies", "heading"))
        head.addStretch(1)
        head.addWidget(self.zoom_slider)
        head.addWidget(self.zoom_label)
        head_box = QWidget()
        head_box.setFixedHeight(theme.CONTROL_H)
        head_box.setLayout(head)
        cv.addWidget(head_box)
        cv.addWidget(self.compare_scroll, 1)
        self._update_zoom_label()

        # ----- the groups and the comparison share the width; the options column stays fixed -----
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.GAP)
        split.addWidget(middle)
        split.addWidget(compare)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        remember("dup_split", split)
        if "v3:dup_split" not in settings.load().get("layout", {}):  # first run: the comparison gets more room
            QTimer.singleShot(0, lambda: split.setSizes([int(split.width() * 0.4), int(split.width() * 0.6)]))
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(theme.GAP)
        columns.addWidget(left_scroll)
        columns.addWidget(split, 1)
        self.body.addLayout(columns, 1)
        self._show_compare()

        self._refresh_engine_status()
        self._update_buttons()

    # ---------- small helpers ----------
    def _show_mode(self, index):
        self.panel_a.setVisible(index == 0)
        self.panel_b.setVisible(index == 1)
        self.files_card.setVisible(index == 1)

    def _percent_spin(self, value, low, high):
        spin = NoWheelSpin()
        spin.setRange(low, high)
        spin.setSuffix("%")
        spin.setValue(int(value))
        return spin

    def _indented(self, text, spin):
        """An option that belongs to the tick box above it: indented, label left, value right."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(22, 0, 0, 0)
        h.setSpacing(theme.GAP)
        h.addWidget(muted(text), 1)
        spin.setFixedWidth(64)
        h.addWidget(spin)
        return row

    def _options(self):
        return de.Options(recursive=self.recursive.isChecked(), percent=self.percent.value(),
                          audio=self.audio.isChecked(), audio_ratio=self.audio_ratio.value() / 100,
                          audio_similarity=self.audio_sim.value() / 100, visual=self.visual.isChecked(),
                          visual_hit=self.visual_hit.value())

    def _save_choices(self):
        settings.save({
            "dup_options": {
                "mode": self.mode.currentData(), "recursive": self.recursive.isChecked(),
                "percent": self.percent.value(), "audio": self.audio.isChecked(),
                "audio_ratio": self.audio_ratio.value(), "audio_similarity": self.audio_sim.value(),
                "visual": self.visual.isChecked(), "visual_hit": self.visual_hit.value(),
            }
        })

    # ---------- zoom ----------
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(obj, event)
        try:
            viewport = self.compare_scroll.viewport()
        except RuntimeError:  # the window is closing
            return False
        if obj is viewport and event.modifiers() & Qt.ControlModifier:
            step = 0.1 if event.angleDelta().y() > 0 else -0.1
            self.zoom_slider.setValue(round((self.zoom + step) * 100))  # the slider's handler applies it
            return True
        return super().eventFilter(obj, event)

    def _set_zoom(self, zoom):
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, zoom))
        for card_widget in self.cards:
            card_widget.set_zoom(self.zoom)
        self._update_zoom_label()
        settings.save({"dup_zoom": round(self.zoom, 2)})

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")

    # ---------- files ----------
    def _add_files(self):
        start = self.library.text() or ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose video files", start, VIDEO_FILTER)
        present = {self.files.item(i).text() for i in range(self.files.count())}
        for path in paths:
            if path not in present:
                self.files.addItem(path)

    def _remove_files(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))

    # ---------- engine ----------
    def _refresh_engine_status(self):
        version = de.installed_version()
        if de.find_engine():
            self.engine_label.setText(f"Engine installed{f' (version {version})' if version else ''}.")
            self.install_btn.setText("Reinstall engine")
        else:
            self.engine_label.setText("Engine not installed yet.")
            self.install_btn.setText("Install engine")
        ok, text = de.ffmpeg_ready()
        self.ffmpeg_label.setText(f"FFmpeg: {text.lower()}" if not ok else "FFmpeg found.")
        self.ffmpeg_btn.setVisible(not ok)

    def _set_busy(self, busy):
        self.running = busy
        self.scan_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.install_btn.setEnabled(not busy)
        self.update_btn.setEnabled(not busy)
        self.ffmpeg_btn.setEnabled(not busy)

    def _install_engine(self):
        self._set_busy(True)
        self.app.run_background(self._install_job)

    def _install_job(self, log, progress):
        try:
            de.install_engine(log, progress)
        finally:
            self.app.on_main(self._after_install)

    def _after_install(self):
        self._set_busy(False)
        self._refresh_engine_status()

    def _install_ffmpeg(self):
        self._set_busy(True)
        self.app.run_background(self._ffmpeg_job)

    def _ffmpeg_job(self, log, progress):
        try:
            de.install_ffmpeg(log, progress)
        finally:
            self.app.on_main(self._after_install)

    def _check_update(self):
        self._set_busy(True)
        self.app.run_background(self._check_job)

    def _check_job(self, log, progress):
        try:
            installed, latest = de.check_update()
            if not installed:
                log("The engine is not installed yet. Use Install engine.")
            elif latest and latest != installed:
                log(f"Engine update available: {installed} -> {latest}.")
                self.app.on_main(lambda: self._ask_update(latest))
            else:
                log(f"Engine is up to date ({installed}).")
        finally:
            self.app.on_main(self._after_install)

    def _ask_update(self, latest):
        answer = QMessageBox.question(self, "Engine update", f"Install engine {latest} now?")
        if answer == QMessageBox.Yes:
            self._set_busy(True)
            self.app.run_background(self._install_job)

    # ---------- scanning ----------
    def _scan(self):
        if self.running:
            return
        engine = de.find_engine()
        if not engine:
            self.app.log("ERROR: the engine is not installed. Use Install engine first.")
            return
        ok, text = de.ffmpeg_ready()
        if not ok:
            self.app.log(f"ERROR: FFmpeg is missing ({text}). Use Download FFmpeg first.")
            return
        mode = self.mode.currentData()
        if mode == "folder":
            folder = self.folder.text().strip()
            if not Path(folder).is_dir():
                self.app.log("ERROR: choose a folder to search.")
                return
            targets = (folder,)
            settings.save({"dup_last_folder": folder})
        else:
            files = [self.files.item(i).text() for i in range(self.files.count())]
            library = self.library.text().strip()
            if not files:
                self.app.log("ERROR: add at least one video to check.")
                return
            if not Path(library).is_dir():
                self.app.log("ERROR: choose the library folder.")
                return
            targets = (files, library)
            settings.save({"dup_last_library": library, "dup_last_files": files})
        cfg = self._options()
        self._save_choices()
        self.state = de.ScanState()
        self._set_busy(True)
        self.app.run_background(self._scan_job, mode, targets, cfg, engine, self.state)

    def _scan_job(self, mode, targets, cfg, engine, state, log, progress):
        try:
            db = de.data_dir() / "fingerprints.db"
            if mode == "folder":
                out = de.data_dir() / "last_scan.json"
                cmd = de.build_command(engine, [targets[0]], cfg, db, out)
                code = de.run_engine(cmd, state, log, progress)
                if state.cancelled:
                    log("Scan cancelled.")
                    return
                if code != 0 or not out.exists():
                    raise RuntimeError(f"The engine stopped with code {code}. See the lines above.")
                groups = de.read_results(out)
            else:
                files, library = targets
                groups = de.check_files_against_library(files, library, cfg, state, log, progress, db)
                if state.cancelled:
                    log("Check cancelled.")
                    return
            ignored = settings.load().get("dup_ignored", [])
            groups = de.filter_ignored(groups, ignored)
            log(f"Found {len(groups)} group(s) of duplicates.")
            self.app.on_main(lambda: self._set_groups(groups))
        finally:
            self.app.on_main(self._scan_done)

    def _scan_done(self):
        self.state = None
        self._set_busy(False)

    def _cancel(self):
        if self.state:
            self.app.log("Cancelling...")
            self.state.cancel()

    def _set_groups(self, groups):
        self.groups = groups
        self.by_key = {g["key"]: g for g in groups}
        self._render()

    # ---------- groups list ----------
    def _render(self):
        flt = self.filter.currentData()
        by = self.sort.currentData()
        # A group shows when one of its copies matches the filter; the best copy is always listed for reference.
        shown = [g for g in self.groups
                 if flt is None or any(i["match"] == flt and not i["best"] for i in g["items"])]
        if by == "size":
            shown.sort(key=lambda g: max(i["size"] for i in g["items"]), reverse=True)
        else:
            shown.sort(key=lambda g: max((i["similarity"] for i in g["items"] if not i["best"]), default=0),
                       reverse=True)
        self.tree.clear()
        copies = 0
        for number, group in enumerate(shown, 1):
            header = QTreeWidgetItem(self.tree)
            visible = [i for i in group["items"] if flt is None or i["match"] == flt or i["best"]]
            header.setText(0, f"Group {number}  ·  {len(group['items'])} copies  ·  "
                              f"{de.MATCH_LABELS.get(de.group_match(group), '')}")
            header.setData(0, ROW_GROUP, group["key"])
            bold = header.font(0)
            bold.setBold(True)
            header.setFont(0, bold)
            header.setExpanded(True)
            for item in sorted(visible, key=lambda i: (not i["best"], -i["pixels"])):
                copies += 1
                row = QTreeWidgetItem(header)
                star = "★  " if item["best"] else "     "
                row.setText(0, star + item["name"] + ("  (picked file)" if item.get("picked") else ""))
                row.setToolTip(0, item["path"])
                row.setData(0, ROW_PATH, item["path"])
                row.setData(0, ROW_GROUP, group["key"])
        self.summary.setText(f"{len(shown)} group(s), {copies} file(s) shown." if self.groups
                             else "No duplicates in the last scan.")
        self._update_buttons()
        self._show_compare()
        self._request_thumbs(shown)

    def _request_thumbs(self, groups):
        todo = []
        for group in groups:
            for item in group["items"]:
                if item["path"] not in self.thumbs and item["path"] not in self.thumbs_busy:
                    self.thumbs_busy.add(item["path"])
                    todo.append((item["path"], item["duration"]))
        if todo:
            threading.Thread(target=self._thumb_worker, args=(todo,), daemon=True).start()

    def _thumb_worker(self, todo):
        for path, duration in todo:
            qimg = None
            try:
                pil = de.extract_thumbnail(path, duration)
                if pil is not None:
                    qimg = _to_qimage(pil)
            except Exception:
                qimg = None  # no thumbnail; the card shows "No preview"
            self.app.on_main(lambda p=path, q=qimg: self._thumb_ready(p, q))

    def _thumb_ready(self, path, qimg):
        self.thumbs_busy.discard(path)
        if qimg is None:
            return
        self.thumbs[path] = qimg
        self._show_compare()

    # ---------- comparison box ----------
    def _on_selection(self):
        self._update_buttons()
        self._show_compare()

    def _show_compare(self):
        while self.compare_row.count():
            entry = self.compare_row.takeAt(0)
            if entry.widget() is not None:
                entry.widget().hide()  # gone from view at once, deleted when Qt is next idle
                entry.widget().deleteLater()
        self.cards = []
        group, _item = self._selection()
        if group is None:
            # Centred in the whole comparison area, so it reads as a placeholder, not stray text
            self.compare_row.addWidget(empty_state("Select a group to compare its copies side by side."), 1)
            return
        for item in sorted(group["items"], key=lambda i: (not i["best"], -i["pixels"])):
            widget = CopyCard(item, self.thumbs.get(item["path"]))
            widget.set_zoom(self.zoom)
            widget.clicked.connect(self._open_card)
            widget.context_requested.connect(self._card_menu)
            self.cards.append(widget)
            self.compare_row.addWidget(widget, 0, Qt.AlignTop)
        self.compare_row.addStretch(1)

    def _open_card(self, path):
        try:
            _open_path(path)
        except OSError as exc:
            self.app.log(f"ERROR: could not open the file: {exc}")

    # ---------- marking, deleting and moving ----------
    def _selected_targets(self):
        """(group keys of selected group rows, paths of selected file rows)."""
        group_keys, files = set(), []
        for row in self.tree.selectedItems():
            if row.parent() is None:
                group_keys.add(row.data(0, ROW_GROUP))
            else:
                files.append(row.data(0, ROW_PATH))
        return group_keys, files

    def _group_of(self, path):
        return next((g for g in self.groups if any(de._normal(i["path"]) == de._normal(path)
                                                   for i in g["items"])), None)

    def _mark_best(self, path):
        group = self._group_of(path)
        if group is None:
            return
        for item in group["items"]:
            item["best"] = de._normal(item["path"]) == de._normal(path)
        self.app.log(f"Marked {Path(path).name} as the best copy.")
        self._render()

    def _tree_menu(self, pos):
        row = self.tree.itemAt(pos)
        if row is not None and not row.isSelected():
            self.tree.clearSelection()
            row.setSelected(True)
            self.tree.setCurrentItem(row)
        group_keys, files = self._selected_targets()
        menu = QMenu(self)
        if row is not None and row.parent() is not None and len(files) == 1:
            group = self.by_key.get(row.data(0, ROW_GROUP))
            item = next((i for i in group["items"] if i["path"] == row.data(0, ROW_PATH)), None) if group else None
            if item is not None and not item["best"]:
                menu.addAction("Mark as best copy", lambda: self._mark_best(item["path"]))
        if files:
            menu.addAction(f"Send {len(files)} file(s) to Recycle Bin", self._delete_selected)
        if group_keys or files:
            menu.addAction("Move to folder...", self._move_selected)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _card_menu(self, path, global_pos):
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_card(path))
        group = self._group_of(path)
        item = next((i for i in group["items"] if de._normal(i["path"]) == de._normal(path)), None) if group else None
        if item is not None and not item["best"]:
            menu.addAction("Mark as best copy", lambda: self._mark_best(path))
        menu.addAction("Send to Recycle Bin", lambda: self._delete_paths([path]))
        menu.exec(global_pos)

    def _delete_selected(self):
        _group_keys, files = self._selected_targets()
        self._delete_paths(files)

    def _delete_paths(self, files):
        if not files:
            self.app.log("Select one or more files to delete.")
            return
        answer = QMessageBox.question(self, "Send to Recycle Bin",
                                      f"Send {len(files)} file(s) to the Recycle Bin?\n"
                                      "Every removal is written to the deletions log.")
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.app.run_background(self._delete_job, files)

    def _delete_job(self, files, log, progress):
        try:
            removed = de.recycle_files(files, log)
            log(f"Sent {len(removed)} file(s) to the Recycle Bin. Log: {de.delete_log_path()}")
            self.app.on_main(lambda: self._apply_removed(removed))
        finally:
            self.app.on_main(lambda: self._set_busy(False))

    def _move_selected(self):
        group_keys, files = self._selected_targets()
        ops = de.plan_moves(self.groups, group_keys, files)
        if not ops:
            self.app.log("Select groups or files to move.")
            return
        target = QFileDialog.getExistingDirectory(self, "Move to folder")
        if not target:
            return
        copies = sum(1 for op in ops if op["copy"])
        answer = QMessageBox.question(
            self, "Move",
            f"{len(ops) - copies} file(s) will be moved and {copies} copied into:\n{target}\n\n"
            "Files in several groups are copied (renamed '(copy)'), so each group keeps its own copy.")
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.app.run_background(self._move_job, ops, target)

    def _move_job(self, ops, target, log, progress):
        try:
            moved = de.execute_moves(ops, target, log)
            log(f"Done: {len(moved)} file(s) moved, the rest copied.")
            self.app.on_main(lambda: self._apply_removed(moved))
        finally:
            self.app.on_main(lambda: self._set_busy(False))

    def _apply_removed(self, paths):
        """Take removed or moved files out of their groups. A group left with one file is dropped."""
        gone = {de._normal(p) for p in paths}
        kept = []
        for group in self.groups:
            items = [dict(i) for i in group["items"] if de._normal(i["path"]) not in gone]
            if len(items) < 2:
                continue
            if not any(i["best"] for i in items):
                max(items, key=lambda i: (i["pixels"], i["bitrate"], i["size"]))["best"] = True
            kept.append({"key": de.group_key([i["path"] for i in items]), "items": items})
        self._set_groups(kept)

    # ---------- selection and actions ----------
    def _selection(self):
        """(group, item or None) for the row that is selected, or (None, None)."""
        row = self.tree.currentItem()
        if row is None:
            return None, None
        group = self.by_key.get(row.data(0, ROW_GROUP))
        if group is None:
            return None, None
        if row.parent() is None:
            return group, None
        path = row.data(0, ROW_PATH)
        item = next((i for i in group["items"] if i["path"] == path), None)
        return group, item

    def _update_buttons(self):
        group, item = self._selection()
        has_file = item is not None
        for widget in (self.btn_open, self.btn_show, self.btn_offset):
            widget.setEnabled(has_file)
        self.btn_offset.setEnabled(has_file and item["offset"] > 0)
        self.btn_keep.setEnabled(group is not None)
        self.btn_ignore.setEnabled(group is not None)
        group_keys, files = self._selected_targets()
        self.btn_delete.setEnabled(bool(files))
        self.btn_move.setEnabled(bool(group_keys or files))

    def _open_selected(self):
        _group, item = self._selection()
        if item:
            self._open_card(item["path"])

    def _show_selected(self):
        _group, item = self._selection()
        if item:
            _show_in_explorer(item["path"])

    def _open_offset(self):
        """Opens the file. Default players cannot be told to jump to a time, so the offset is logged."""
        _group, item = self._selection()
        if not item:
            return
        self.app.log(f"{item['name']} is a clip that starts at {de.format_seconds(item['offset'])} in the longer "
                     f"video. Opening it; seek to that time in your player.")
        self._open_card(item["path"])

    def _keep_selected(self):
        group, item = self._selection()
        if group is None:
            return
        keep = item["path"] if item else next(i["path"] for i in group["items"] if i["best"])
        others = [i for i in group["items"] if i["path"] != keep]
        answer = QMessageBox.question(
            self, "Keep this one",
            f"Keep:\n{keep}\n\nSend {len(others)} other copy(ies) to the Recycle Bin?\n"
            "Every removal is written to the deletions log.")
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.app.run_background(self._keep_job, group, keep)

    def _keep_job(self, group, keep, log, progress):
        try:
            sent = de.keep_one(group, keep, log)
            log(f"Sent {sent} copy(ies) to the Recycle Bin. Log: {de.delete_log_path()}")
            self.app.on_main(lambda: self._drop_group(group["key"]))
        finally:
            self.app.on_main(lambda: self._set_busy(False))

    def _drop_group(self, key):
        self.groups = [g for g in self.groups if g["key"] != key]
        self.by_key.pop(key, None)
        self._render()

    def _ignore_group(self):
        group, _item = self._selection()
        if group is None:
            return
        ignored = settings.load().get("dup_ignored", [])
        if group["key"] not in ignored:
            ignored.append(group["key"])
            settings.save({"dup_ignored": ignored})
        self.app.log("Group ignored. It will not show up in future scans.")
        self._drop_group(group["key"])

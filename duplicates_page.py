"""The Duplicate videos screen: a front end for the vdf-cli engine (duplicates_engine.py).

Three columns: what to match (left), the groups and their copies (middle), and the copies side by side (right).
Removed copies go to the Recycle Bin and are written to the deletions log; moves go to the move log with Undo.
The best copy stays where it is (PRODUCT.md)."""
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QScrollArea, QSlider, QSpinBox, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import dialogs
import duplicates_engine as de
import engine_ui
import fileops
import gpu
import icons
import jobs
import preview
import settings
import theme
import thumbs
from media_utils import VIDEO_EXTENSIONS, open_path, show_in_explorer
from pages_common import ToolPage, plural
from widgets import (Banner, ElidedLabel, EmptyState, FlowLayout, Segmented, Ticking, add_folder, button, divider,
                     field_label, label, line_edit, muted, remember, remembered, results_panel, set_tag, tag,
                     tool_row, toolbar, wrap_row)

LEFT_W = 290
MIDDLE_MIN_W = 420
COMPARE_MIN_W = 262
CARD_W = 250
ZOOM_MIN, ZOOM_MAX = 0.5, 2.0
ROW_PATH = Qt.UserRole
ROW_GROUP = Qt.UserRole + 1
VIDEO_FILTER = "Videos (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS)) + ");;All files (*.*)"

EXPLAIN_EXACT = ("Exact and near copies are always found. Exact copies are the same video; near copies are "
                 "re-encodes, other sizes or bitrates. Lower the similarity to catch more, with more wrong matches.")
EXPLAIN_AUDIO = ("Finds a shorter clip cut from a longer video by comparing the sound. Videos with no sound are "
                 "skipped in this mode.")
EXPLAIN_VISUAL = ("Finds clips cut from a longer video by comparing the pictures with AI. Works without sound. "
                  "The first time, the engine downloads about 100 MB of AI parts.")


class NoWheel:
    def wheelEvent(self, event):
        event.ignore()  # scrolling the column never changes a value by accident


class NoWheelSlider(NoWheel, QSlider):
    pass


class NoWheelSpin(NoWheel, QSpinBox):
    pass


class CopyCard(QFrame):
    """One copy: a picture (a silent preview plays while the pointer rests on it), the name, a Best copy tag,
    and the details that tell the copies apart. Click to open; right-click for more."""
    clicked = Signal(str)
    context_requested = Signal(str, object)

    def __init__(self, item, image):
        super().__init__()
        self.setObjectName("copy")
        self.setProperty("best", "true" if item["best"] else "false")
        self.path = item["path"]
        self.pixmap = QPixmap.fromImage(image) if image is not None else None
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{item['path']}\nClick to open. Right-click for more.")
        v = QVBoxLayout(self)
        self.v = v
        self.thumb = QLabel()
        self.thumb.setObjectName("stage")
        self.thumb.setAlignment(Qt.AlignCenter)
        v.addWidget(self.thumb)
        preview.hover().watch(self.thumb, item["path"])
        tags = QHBoxLayout()
        tags.setSpacing(6)
        if item["best"]:
            tags.addWidget(tag("Best copy", "acc"))
        if item.get("picked"):
            tags.addWidget(tag("Picked video", "plain"))
        tags.addStretch(1)
        if tags.count() > 1:
            v.addLayout(tags)
        self.title = label(item["name"], "heading", wrap=True)
        v.addWidget(self.title)
        self.folder = ElidedLabel(item["folder"], "caption", Qt.ElideMiddle)
        v.addWidget(self.folder)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 2, 0, 0)
        for row, (key, value) in enumerate(self._details(item)):
            self.grid.addWidget(label(key, "caption"), row, 0, Qt.AlignLeft | Qt.AlignTop)
            self.grid.addWidget(label(value, "value", wrap=True), row, 1)
        self.grid.setColumnStretch(1, 1)
        v.addLayout(self.grid)
        v.addStretch(1)
        self.set_zoom(1.0)

    def _details(self, item):
        rows = [("Match", de.MATCH_LABELS.get(item["match"], item["match"])),
                ("Similarity", f"{item['similarity']:.1f}%"),
                ("Resolution", item["resolution"] or "unknown"),
                ("Size", fileops.human_size(item["size"])),
                ("Length", de.format_seconds(item["duration"])),
                ("Bitrate", f"{item['bitrate']:.0f} kb/s" if item["bitrate"] else "unknown")]
        if item["offset"]:
            rows.append(("Starts at", f"{de.format_seconds(item['offset'])} in the longer video"))
        return rows

    def set_image(self, image):
        self.pixmap = QPixmap.fromImage(image) if image is not None else None
        self.set_zoom(self._zoom, self._max)

    def set_zoom(self, zoom, max_width=None):
        self._zoom, self._max = zoom, max_width
        width = int(CARD_W * zoom)
        if max_width:
            width = max(120, min(width, max_width))
            zoom = width / CARD_W
        pad = max(6, int(10 * zoom))
        self.setFixedWidth(width)
        inner = width - 2 * pad - 2
        height = int(inner * 9 / 16)
        self.thumb.setFixedSize(inner, height)
        if self.pixmap is not None:
            self.thumb.setPixmap(self.pixmap.scaled(inner, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setPixmap(icons.pixmap("silent", theme.FAINT, 24))
        self.v.setContentsMargins(pad, pad, pad, pad)
        self.v.setSpacing(max(2, int(4 * zoom)))
        self.grid.setHorizontalSpacing(max(6, int(10 * zoom)))
        self.grid.setVerticalSpacing(max(1, int(2 * zoom)))
        body = max(9, round(theme.text_px("body") * zoom))
        small = max(9, round(theme.text_px("caption") * zoom))
        self.setStyleSheet(f"QLabel {{ font-size: {small}px; }} QLabel[role='heading'] {{ font-size: {body}px; }}")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.context_requested.emit(self.path, event.globalPos())


class DuplicatesPage(ToolPage):
    title = "Duplicate videos"
    subtitle = ("Find copies of a video, including smaller re-encodes and trimmed clips. Removed copies go to the "
                "Recycle Bin; moves can be undone.")
    key = "dup"
    icon = "duplicate"

    def build(self):
        self.groups = []
        self.by_key = {}
        self.cards = []
        self.thumbs = thumbs.shared()
        self.thumbs.ready.connect(self._thumb_ready)
        saved = settings.load()
        opts = saved.get("dup_options", {})
        self.zoom_level = min(ZOOM_MAX, max(ZOOM_MIN, float(saved.get("dup_zoom", 1.0))))

        # ----- the banner when the engine isn't installed -----
        self.engine_banner = Banner("The duplicate engine isn't installed.",
                                    "It's downloaded when you ask (about 40 MB), into the Models folder beside the app.",
                                    "Install engine…", lambda: engine_ui.install(self.app), "duplicate")
        self.banners.addWidget(self.engine_banner)
        engine_ui.on_change(self.refresh_engine)

        # ----- toolbar -----
        self.mode = Segmented([("folder", "Find in a folder"), ("library", "Check videos against a library")],
                              opts.get("mode", "folder"))
        self.mode.changed.connect(self._show_mode)
        self.folder = line_edit(saved.get("dup_last_folder", ""), "Choose the folder to search")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(opts.get("recursive", True))
        self.library = line_edit(saved.get("dup_last_library", ""), "Choose the library folder")
        self.scan_btn = button("Scan", "primary", icons.icon("search", theme.ON_ACCENT, 16))
        self.scan_btn.clicked.connect(self.scan)
        bar, rows = toolbar()
        top = tool_row()
        top.addWidget(field_label("Mode"))
        top.addWidget(self.mode)
        top.addStretch(1)
        top.addWidget(self.scan_btn)
        rows.addLayout(top)
        what = tool_row()
        self.panel_a = QWidget()
        a = tool_row()
        self.panel_a.setLayout(a)
        add_folder(a, "Folder", self.folder, "Choose the folder to search")
        a.addWidget(self.recursive)
        self.panel_b = QWidget()
        b = tool_row()
        self.panel_b.setLayout(b)
        add_folder(b, "Library", self.library, "Choose the library to check against")
        add = button("Add videos…", icon=icons.icon("folder_plus", theme.TEXT, 16))
        add.setToolTip("Choose the videos to check against the library")
        add.clicked.connect(self._add_files)
        b.addWidget(add)
        what.addWidget(self.panel_a, 1)
        what.addWidget(self.panel_b, 1)
        rows.addLayout(what)
        self.body.addWidget(bar)
        self.panels.append(bar)

        # ----- left: videos to check and matching options -----
        self.files = QTreeWidget()
        self.files.setHeaderLabels(["Video", "State"])
        self.files.setRootIsDecorated(False)
        self.files.setUniformRowHeights(True)
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.setSelectionMode(QTreeWidget.ExtendedSelection)
        fh = self.files.header()
        fh.setStretchLastSection(False)
        fh.setSectionResizeMode(0, fh.ResizeMode.Stretch)
        self.files.setColumnWidth(1, 92)
        self.files.setToolTip("Ticked videos are checked on the next scan. Videos already checked are unticked and "
                              "say how many matches they had.")
        self.files.itemChanged.connect(lambda *_: (self._save_file_list(), self.refresh_buttons()))
        done = saved.get("dup_files_done", {})
        for path in saved.get("dup_last_files", []):
            if Path(path).exists():
                self._add_file_item(path, done.get(path))
        self.one_by_one = QCheckBox("One video at a time")
        self.one_by_one.setChecked(opts.get("one_by_one", True))
        self.one_by_one.setToolTip("Checks each video on its own, so its matches show as soon as it's done and you "
                                   "can stop and check the rest later. The library is fingerprinted once.")
        self.files_card, fv = results_panel()
        fhead = tool_row()
        fhead.addWidget(label("Videos to check", "heading"), 1)
        remove = button("Remove", "ghost", tip="Take the selected videos off the list (nothing on disk changes)")
        remove.clicked.connect(self._remove_files)
        fhead.addWidget(remove)
        fv.addLayout(fhead)
        self.files.setMinimumHeight(96)
        fv.addWidget(self.files, 1)
        ffoot = tool_row()
        ffoot.addWidget(self.one_by_one, 1)
        again = button("Check all again", "ghost", tip="Tick every video again and clear earlier results")
        again.clicked.connect(self._check_all_again)
        ffoot.addWidget(again)
        fv.addLayout(ffoot)

        self.percent = NoWheelSlider(Qt.Horizontal)
        self.percent.setRange(50, 100)
        self.percent.setValue(int(opts.get("percent", 95)))
        self.percent.setToolTip(EXPLAIN_EXACT)
        self.percent_label = label(f"{self.percent.value()}%", "value")
        self.percent_label.setFixedWidth(36)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent.valueChanged.connect(lambda v: self.percent_label.setText(f"{v}%"))
        self.audio = QCheckBox("Partial clips by sound")
        self.audio.setChecked(opts.get("audio", False))
        self.audio.setToolTip(EXPLAIN_AUDIO)
        self.audio_ratio = self._percent_spin(opts.get("audio_ratio", 10), 1, 100, "The shortest clip to look for, "
                                              "as a share of the longer video")
        self.audio_sim = self._percent_spin(opts.get("audio_similarity", 80), 1, 100, "How closely the sound must match")
        self.visual = QCheckBox("Partial clips by picture (AI)")
        self.visual.setChecked(opts.get("visual", False))
        self.visual.setToolTip(EXPLAIN_VISUAL)
        self.visual_hit = self._percent_spin(opts.get("visual_hit", 89), 70, 99, "How closely each frame must match")
        options, ov = results_panel()
        ov.setSpacing(6)
        ov.addWidget(label("Matching", "heading"))
        sim = tool_row()
        sim.addWidget(muted("Similarity"))
        sim.addWidget(self.percent, 1)
        sim.addWidget(self.percent_label)
        ov.addLayout(sim)
        ov.addWidget(label("Lower finds more, with more wrong matches.", "caption", wrap=True))
        ov.addSpacing(4)
        ov.addWidget(self.audio)
        ov.addWidget(self._indented("Shortest clip", self.audio_ratio))
        ov.addWidget(self._indented("Sound match", self.audio_sim))
        ov.addSpacing(4)
        ov.addWidget(self.visual)
        ov.addWidget(self._indented("Frame match", self.visual_hit))
        self.gpu_note = label("", "caption", wrap=True)
        ov.addWidget(self.gpu_note)
        left_host = QWidget()
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 11, 0)  # the scroll bar sits in this margin
        left.setSpacing(theme.GAP)
        left.addWidget(self.files_card)
        left.addWidget(options)
        left.addStretch(1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_host)
        left_scroll.setMinimumWidth(LEFT_W)
        self.left_scroll = left_scroll

        # ----- middle: groups -----
        self.filter = Segmented([(None, "All"), ("exact", "Exact"), ("near", "Near"), ("partial_audio", "Sound"),
                                 ("partial_visual", "Picture")], None)
        self.filter.changed.connect(lambda _v: self._render())
        self.filter.setToolTip("Show only groups with this kind of match")
        self.sort = QComboBox()
        self.sort.addItem("Largest first", "size")
        self.sort.addItem("Most similar", "similarity")
        self.sort.addItem("Most copies", "count")
        self.sort.currentIndexChanged.connect(lambda _i: self._render())
        self.summary = ElidedLabel("No scan yet.")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Groups"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(16)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.currentItemChanged.connect(lambda *_: self._on_selection())
        self.tree.itemDoubleClicked.connect(lambda _i, _c: self._open_selected())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.ticking = Ticking(self.tree)
        self.ticking.ticks_changed.connect(self.refresh_buttons)
        self.tree.itemChanged.connect(self._group_ticked)
        self.btn_keep = button("Keep", "primary")
        self.btn_keep.setToolTip("Keep the selected copy (or the best copy) and send the others to the Recycle Bin")
        self.btn_keep.clicked.connect(self._keep_selected)
        self.btn_recycle = button("Recycle", "danger-ghost")
        self.btn_recycle.setToolTip("Send the ticked (or selected) copies to the Recycle Bin")
        self.btn_recycle.clicked.connect(self._recycle_targets)
        self.btn_move = button("Move")
        self.btn_move.setToolTip("Move the ticked groups and copies to a folder, after a review")
        self.btn_move.clicked.connect(self._move_targets)
        self.btn_ignore = button("Ignore", "ghost")
        self.btn_ignore.setToolTip("Hide this group now and in every future scan")
        self.btn_ignore.clicked.connect(self._ignore_group)
        more = QToolButton()
        more.setText("More")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more_menu = QMenu(more)
        self.act_open = more_menu.addAction("Open video", self._open_selected)
        self.act_show = more_menu.addAction("Show in Explorer", self._show_selected)
        self.act_offset = more_menu.addAction("Open the clip (its start is in the log)", self._open_offset)
        self.act_best = more_menu.addAction("Make this the best copy", self._mark_selected_best)
        more_menu.addSeparator()
        more_menu.addAction("Tick all groups", lambda: self.ticking.tick_all(True))
        more_menu.addAction("Untick all", lambda: self.ticking.tick_all(False))
        more.setMenu(more_menu)
        middle, mv = results_panel()
        middle.setMinimumWidth(MIDDLE_MIN_W)
        mv.addWidget(self.filter, 0, Qt.AlignLeft)
        top2 = tool_row()
        top2.setSpacing(6)
        top2.addWidget(self.summary, 1)
        top2.addWidget(self.sort)
        mv.addLayout(top2)
        mv.addWidget(self.tree, 1)
        acts_host, acts = wrap_row()  # wraps onto a second line rather than squeezing the buttons
        for w in (self.btn_keep, self.btn_recycle, self.btn_move, self.btn_ignore, more):
            acts.addWidget(w)
        mv.addWidget(acts_host)

        # ----- right: the copies side by side -----
        self.compare_host = QWidget()
        self.compare_row = FlowLayout(self.compare_host, spacing=theme.GAP)
        self.compare_scroll = QScrollArea()
        self.compare_scroll.setWidgetResizable(True)
        self.compare_scroll.setFrameShape(QFrame.NoFrame)
        self.compare_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.compare_scroll.setWidget(self.compare_host)
        self.compare_scroll.viewport().installEventFilter(self)
        self.compare_empty = EmptyState("duplicate", "Select a group to compare its copies.")
        self.zoom_slider = NoWheelSlider(Qt.Horizontal)
        self.zoom_slider.setRange(int(ZOOM_MIN * 100), int(ZOOM_MAX * 100))
        self.zoom_slider.setValue(round(self.zoom_level * 100))
        self.zoom_slider.valueChanged.connect(lambda v: self._set_zoom(v / 100))
        self.zoom_slider.setFixedWidth(90)
        self.zoom_slider.setToolTip("Card size (Ctrl + mouse wheel over the cards, or + and −)")
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
        cv.addWidget(self.compare_empty, 1)
        self._update_zoom_label()

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.GAP)
        split.addWidget(left_scroll)
        split.addWidget(middle)
        split.addWidget(compare)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 2)
        split.setStretchFactor(2, 3)
        remember("dup_columns", split)
        if not remembered("dup_columns"):
            def share():
                rest = max(0, split.width() - LEFT_W - 2 * theme.GAP)
                split.setSizes([LEFT_W, int(rest * 0.42), int(rest * 0.58)])
            QTimer.singleShot(0, share)
        self.body.addWidget(split, 1)
        self.panels.append(left_scroll)
        self._show_mode(self.mode.value())
        self.refresh_engine()
        self._show_compare()

    # ---------- helpers ----------
    def _percent_spin(self, value, low, high, tip):
        spin = NoWheelSpin()
        spin.setRange(low, high)
        spin.setSuffix("%")
        spin.setValue(int(value))
        spin.setToolTip(tip)
        return spin

    def _indented(self, text, spin):
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
        settings.save({"dup_options": {
            "mode": self.mode.value(), "recursive": self.recursive.isChecked(),
            "one_by_one": self.one_by_one.isChecked(), "percent": self.percent.value(),
            "audio": self.audio.isChecked(), "audio_ratio": self.audio_ratio.value(),
            "audio_similarity": self.audio_sim.value(), "visual": self.visual.isChecked(),
            "visual_hit": self.visual_hit.value()}})

    def _show_mode(self, mode):
        self.panel_a.setVisible(mode == "folder")
        self.panel_b.setVisible(mode == "library")
        self.files_card.setVisible(mode == "library")
        self._set_groups(de.load_results(mode))
        self._save_choices()
        self.refresh_buttons()

    def refresh_engine(self):
        installed = bool(de.find_engine())
        self.engine_banner.setVisible(not installed)
        self.app.set_attention("dup", not installed)
        ok, gpu_reason = gpu.use_gpu() if installed else (False, "")
        self.gpu_note.setText(("Decoding on the GPU. " if ok else "") + gpu_reason if installed else "")

    def refresh_buttons(self):
        if self.mode.value() == "folder":
            self.set_main(self.scan_btn, "Scan the folder", "a scan")
        else:
            n = sum(1 for i in self._file_items() if i.checkState(0) == Qt.Checked)
            self.set_main(self.scan_btn, f"Check {plural(n, 'video')}" if n else "Check videos",
                          f"checking {plural(n, 'video')}")
        group_keys, files = self._targets()
        self.btn_recycle.setText(f"Recycle {plural(len(files), 'copy', 'copies')}" if files else "Recycle")
        n = len(group_keys) + len(files)
        self.btn_move.setText(f"Move {plural(len(group_keys), 'group')}" + (f" + {plural(len(files), 'copy', 'copies')}"
                                                                            if files else "")
                              if group_keys else (f"Move {plural(len(files), 'copy', 'copies')}" if files else "Move"))
        group, item = self._selection()
        self.btn_keep.setText("Keep this copy" if item else ("Keep the best copy" if group else "Keep"))
        has = n > 0 or group is not None
        for w in (self.btn_keep, self.btn_recycle, self.btn_move, self.btn_ignore):
            w.setVisible(bool(self.groups))
        self.act_open.setEnabled(item is not None)
        self.act_show.setEnabled(item is not None)
        self.act_offset.setEnabled(bool(item and item["offset"] > 0))
        self.act_best.setEnabled(bool(item and not item["best"]))
        _ = has

    # ---------- zoom ----------
    def _card_room(self):
        return max(120, self.compare_scroll.viewport().width() - 12)

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.Wheel, QEvent.Resize):
            return super().eventFilter(obj, event)
        try:
            viewport = self.compare_scroll.viewport()
        except RuntimeError:
            return False
        if obj is viewport and event.type() == QEvent.Resize:
            for card in self.cards:
                card.set_zoom(self.zoom_level, self._card_room())
            return False
        if obj is viewport and event.modifiers() & Qt.ControlModifier:
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(obj, event)

    def zoom(self, step):
        self.zoom_slider.setValue(round((self.zoom_level + 0.1 * step) * 100))
        return True

    def _set_zoom(self, z):
        self.zoom_level = min(ZOOM_MAX, max(ZOOM_MIN, z))
        for card in self.cards:
            card.set_zoom(self.zoom_level, self._card_room())
        self._update_zoom_label()
        settings.save({"dup_zoom": round(self.zoom_level, 2)})

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{round(self.zoom_level * 100)}%")

    # ---------- videos to check ----------
    def _add_files(self):
        start = self.library.text() or ""
        chosen, _ = QFileDialog.getOpenFileNames(self, "Choose videos to check", start, VIDEO_FILTER)
        present = set(self._file_paths())
        self.files.blockSignals(True)
        for path in chosen:
            if path not in present:
                self._add_file_item(path)
        self.files.blockSignals(False)
        self._save_file_list()
        self.refresh_buttons()

    def _remove_files(self):
        for item in self.files.selectedItems():
            self.files.takeTopLevelItem(self.files.indexOfTopLevelItem(item))
        self._save_file_list()
        self.refresh_buttons()

    def _add_file_item(self, path, matches=None):
        item = QTreeWidgetItem([Path(path).name, ""])
        item.setData(0, Qt.UserRole, path)
        item.setToolTip(0, path)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        self.files.addTopLevelItem(item)
        self._file_state(item, "Done" if matches is not None else "", matches)

    def _file_state(self, item, state, matches=None):
        """Ticked = still to check. Done videos are unticked and say how many matches they had."""
        item.setData(0, Qt.UserRole + 1, matches)
        if state == "Done":
            item.setText(1, f"{matches} match{'es' if matches != 1 else ''}")
            item.setCheckState(0, Qt.Unchecked)
            colour = theme.OK
        else:
            item.setText(1, state or "To check")
            if not state:
                item.setCheckState(0, Qt.Checked)
            colour = {"Checking": theme.ACCENT, "Failed": theme.DANGER, "Queued": theme.SEC}.get(state, theme.FAINT)
        item.setForeground(1, QColor(colour))

    def _file_items(self):
        return [self.files.topLevelItem(i) for i in range(self.files.topLevelItemCount())]

    def _file_paths(self):
        return [i.data(0, Qt.UserRole) for i in self._file_items()]

    def _file_item(self, path):
        return next((i for i in self._file_items() if i.data(0, Qt.UserRole) == path), None)

    def _save_file_list(self):
        done = {i.data(0, Qt.UserRole): i.data(0, Qt.UserRole + 1) for i in self._file_items()
                if i.data(0, Qt.UserRole + 1) is not None}
        settings.save({"dup_last_files": self._file_paths(), "dup_files_done": done})

    def _check_all_again(self):
        if not dialogs.ask("Check every video again?", "Every video on the list is ticked again and the results of "
                           "earlier checks are cleared. Nothing on disk changes.", "Check all again"):
            return
        self.files.blockSignals(True)
        for item in self._file_items():
            self._file_state(item, "")
        self.files.blockSignals(False)
        self._save_file_list()
        de.save_results("library", [])
        self._set_groups([])
        self.refresh_buttons()

    def _file_checked(self, path, groups):
        groups = de.filter_ignored(groups, settings.load().get("dup_ignored", []))
        merged = {g["key"]: g for g in self.groups}
        for g in groups:
            merged[g["key"]] = g
        self._set_groups(list(merged.values()))
        item = self._file_item(path)
        if item is not None:
            self.files.blockSignals(True)
            self._file_state(item, "Done", len(groups))
            self.files.blockSignals(False)
        self._save_file_list()
        de.save_results("library", self.groups)
        self.refresh_buttons()

    def _mark_files(self, paths, state):
        self.files.blockSignals(True)
        for p in paths:
            item = self._file_item(p)
            if item is not None and item.data(0, Qt.UserRole + 1) is None:
                self._file_state(item, state)
        self.files.blockSignals(False)

    # ---------- scanning ----------
    def scan(self):
        engine = de.find_engine()
        if not engine:
            if dialogs.ask("Install the duplicate engine first?", "Finding duplicates uses vdf-cli, which is "
                           "downloaded when you ask. The next step says how big it is and where it goes.",
                           "Look up the engine", icon_name="duplicate"):
                engine_ui.install(self.app)
            return
        ok, text = de.ffmpeg_ready()
        if not ok:
            if dialogs.ask("FFmpeg is missing", f"The engine needs FFmpeg ({text.lower()}).", "Get FFmpeg…",
                           icon_name="warn"):
                engine_ui.install_ffmpeg(self.app)
            return
        mode = self.mode.value()
        cfg = self._options()
        self._save_choices()
        state = de.ScanState()
        if mode == "folder":
            folder = self.folder.text().strip()
            if not Path(folder).is_dir():
                dialogs.info("Choose a folder", "Pick the folder to search for duplicates." if not folder else
                             f"{folder} can't be found. Its drive may be unplugged.", icon_name="folder")
                return
            settings.save({"dup_last_folder": folder})
            job = jobs.Job("Finding duplicates", self._folder_job, engine, folder, cfg, state, short="Scanning",
                           own_log=True, gpu="cpu", done=lambda j: self.refresh_buttons())
        else:
            files = [i.data(0, Qt.UserRole) for i in self._file_items() if i.checkState(0) == Qt.Checked]
            library = self.library.text().strip()
            if not self._file_items():
                dialogs.info("Add videos to check", "Use Add videos… to choose the videos to look for in the "
                             "library.", icon_name="folder_plus")
                return
            if not files:
                dialogs.info("Every video has been checked", "Tick the videos to check again, or use Check all "
                             "again.", icon_name="check")
                return
            if not Path(library).is_dir():
                dialogs.info("Choose the library", "Pick the library folder to check against." if not library else
                             f"{library} can't be found. Its drive may be unplugged.", icon_name="folder")
                return
            settings.save({"dup_last_library": library})
            self._mark_files(files, "Queued")
            job = jobs.Job(f"Checking {plural(len(files), 'video')} against the library", self._library_job, engine,
                           files, library, cfg, state, self.one_by_one.isChecked(), short="Checking", own_log=True,
                           gpu="cpu", done=self._library_done)
        job.pause_target = state
        self.app.start(job)

    def _with_gpu(self, run, log):
        """Run with the GPU when it's on; if GPU decoding fails, run again on the CPU instead of failing."""
        job = jobs.current()
        use, reason = gpu.use_gpu()
        log(reason)
        job.gpu = "gpu" if use else "cpu"
        try:
            return run(use)
        except de.EngineFailed:
            if not use or job.stop_requested:
                raise
            log("GPU decoding failed, so the scan runs again on the CPU. Fingerprints already made are kept.")
            job.gpu = "cpu"
            return run(False)

    def _folder_job(self, engine, folder, cfg, state, log, progress):
        out = de.data_dir() / "last_scan.json"

        def stage_progress(done, total, stage, eta=None):
            # The engine counts each stage from zero; its own estimate for the stage is shown when it gives one.
            progress(done, total, stage, eta=eta if eta is not None else False)

        def run(use_gpu):
            cmd = de.build_command(engine, [folder], cfg, de.db_path(), out, use_gpu)
            code = de.run_engine(cmd, state, log, stage_progress)
            if state.cancelled:
                return None
            if code != 0 or not out.exists():
                raise de.EngineFailed(code)
            return de.read_results(out)

        de.prepare_ffmpeg(log)
        groups = self._with_gpu(run, log)
        if groups is None:
            log("Scan stopped. Fingerprints made so far are saved, so scanning again carries on from there.")
            return "stopped"
        groups = de.filter_ignored(groups, settings.load().get("dup_ignored", []))
        de.save_results("folder", groups)
        self.app.on_main(lambda: self._set_groups(groups))
        return {"summary": f"{plural(len(groups), 'group')} of duplicates found"}

    def _library_job(self, engine, files, library, cfg, state, one_by_one, log, progress):
        de.prepare_ffmpeg(log)
        total = len(files)
        if not one_by_one:
            self.app.on_main(lambda: self._mark_files(files, "Checking"))

            def stage(done, stotal, name, eta=None):
                progress(done, stotal, name, eta=eta if eta is not None else False)
            groups = self._with_gpu(lambda use: de.check_files_against_library(
                files, library, cfg, state, log, stage, de.db_path(), use), log)
            if groups is None:
                return "stopped"
            for path in files:
                mine = [g for g in groups if any(de._normal(i["path"]) == de._normal(path) for i in g["items"])]
                self.app.on_main(lambda p=path, g=mine: self._file_checked(p, g))
            return {"summary": f"{plural(total, 'video')} checked, {plural(len(groups), 'group')} found"}

        timings, done_count = [], 0
        job = jobs.current()
        last = [job.elapsed()]
        for index, path in enumerate(files):
            if state.cancelled:
                break
            self.app.on_main(lambda p=path: self._mark_files([p], "Checking"))

            def file_progress(done, stotal, name, eta=None, index=index):
                within = done / stotal if stotal else 0.0
                overall = (index + within) / total
                guess = False
                if timings:
                    sample = timings[1:] or timings  # the first video also fingerprints the library
                    guess = sum(sample) / len(sample) * (total - index - within)
                progress(done, stotal, f"Video {index + 1} of {total} · {name}", overall=overall, eta=guess)

            log(f"Checking video {index + 1} of {total}: {Path(path).name}")
            try:
                groups = self._with_gpu(lambda use, p=path: de.check_files_against_library(
                    [p], library, cfg, state, log, file_progress, de.db_path(), use), log)
            except de.EngineFailed as exc:
                log(f"{Path(path).name}: {exc}")
                self.app.on_main(lambda p=path: self._mark_files([p], "Failed"))
                continue
            if groups is None:
                break
            now = job.elapsed()
            timings.append(now - last[0])
            last[0] = now
            done_count += 1
            log(f"{Path(path).name}: {plural(len(groups), 'group')} of matches.")
            self.app.on_main(lambda p=path, g=groups: self._file_checked(p, g))
        if state.cancelled:
            log(f"Stopped after {done_count} of {total} video(s). Their results are shown; the rest stay ticked.")
            return "stopped"
        return {"summary": f"{plural(done_count, 'video')} checked"}

    def _library_done(self, job):
        # videos that were queued but not reached go back to "To check"
        self.files.blockSignals(True)
        for item in self._file_items():
            if item.text(1) in ("Queued", "Checking"):
                self._file_state(item, "")
        self.files.blockSignals(False)
        self.refresh_buttons()

    # ---------- groups ----------
    def _set_groups(self, groups):
        self.groups = groups
        self.by_key = {g["key"]: g for g in groups}
        self._render()

    def _counts(self):
        counts = {None: len(self.groups)}
        for g in self.groups:
            for m in {i["match"] for i in g["items"] if not i["best"]}:
                counts[m] = counts.get(m, 0) + 1
        return counts

    def _render(self):
        counts = self._counts()
        for k in (None, "exact", "near", "partial_audio", "partial_visual"):
            self.filter.set_count(k, counts.get(k, 0))
        flt = self.filter.value()
        by = self.sort.currentData()
        shown = [g for g in self.groups if flt is None or any(i["match"] == flt and not i["best"] for i in g["items"])]
        if by == "size":
            shown.sort(key=lambda g: max(i["size"] for i in g["items"]), reverse=True)
        elif by == "count":
            shown.sort(key=lambda g: len(g["items"]), reverse=True)
        else:
            shown.sort(key=lambda g: max((i["similarity"] for i in g["items"] if not i["best"]), default=0),
                       reverse=True)
        ticked = {(r.data(0, ROW_GROUP), r.data(0, ROW_PATH)) for r in self.ticking.ticked()}
        current = self.tree.currentItem()
        cur_key = (current.data(0, ROW_GROUP), current.data(0, ROW_PATH)) if current else None
        self.tree.blockSignals(True)
        self.tree.clear()
        copies, restore = 0, None
        for number, group in enumerate(shown, 1):
            header = QTreeWidgetItem(self.tree)
            header.setText(0, f"Group {number}  ·  {len(group['items'])} copies  ·  "
                              f"{de.MATCH_LABELS.get(de.group_match(group), '')}")
            header.setData(0, ROW_GROUP, group["key"])
            header.setFlags(header.flags() | Qt.ItemIsUserCheckable)
            header.setCheckState(0, Qt.Checked if (group["key"], None) in ticked else Qt.Unchecked)
            f = header.font(0)
            f.setWeight(f.Weight.DemiBold)
            header.setFont(0, f)
            if cur_key == (group["key"], None):
                restore = header
            for item in sorted(group["items"], key=lambda i: (not i["best"], -i["pixels"])):
                copies += 1
                row = QTreeWidgetItem(header)
                row.setText(0, item["name"] + ("   · best copy" if item["best"] else "")
                            + ("   · picked" if item.get("picked") else ""))
                if item["best"]:
                    row.setForeground(0, QColor(theme.ACCENT))
                row.setToolTip(0, item["path"])
                row.setData(0, ROW_PATH, item["path"])
                row.setData(0, ROW_GROUP, group["key"])
                row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
                row.setCheckState(0, Qt.Checked if (group["key"], item["path"]) in ticked else Qt.Unchecked)
                if cur_key == (group["key"], item["path"]):
                    restore = row
            header.setExpanded(True)
        self.tree.blockSignals(False)
        self.ticking.retint()
        if restore is not None:
            self.tree.setCurrentItem(restore)
        self.summary.setText(f"{plural(len(shown), 'group')}, {plural(copies, 'copy', 'copies')} shown"
                             if self.groups else ("No duplicates in the last scan." if self.groups == [] and
                                                  self._has_run() else "No scan yet."))
        self.refresh_buttons()
        self._show_compare()

    def _has_run(self):
        return (de.data_dir() / f"{self.mode.value()}_results.json").exists()

    def _group_ticked(self, row, column):
        """Ticking a group ticks its copies too."""
        if column != 0 or row.parent() is not None:
            return
        self.tree.blockSignals(True)
        for i in range(row.childCount()):
            row.child(i).setCheckState(0, row.checkState(0))
        self.tree.blockSignals(False)
        self.ticking.retint()
        self.refresh_buttons()

    def _thumb_ready(self, path):
        for card in self.cards:
            if card.path == path:
                card.set_image(self.thumbs.get(path))

    # ---------- comparison ----------
    def _on_selection(self):
        self.refresh_buttons()
        self._show_compare()

    def _show_compare(self):
        preview.hover().stop()
        while self.compare_row.count():
            entry = self.compare_row.takeAt(0)
            if entry.widget() is not None:
                entry.widget().hide()
                entry.widget().deleteLater()
        self.cards = []
        group, _item = self._selection()
        if group is None:
            self.compare_scroll.hide()
            self.compare_empty.show()
            return
        self.compare_empty.hide()
        self.compare_scroll.show()
        for item in sorted(group["items"], key=lambda i: (not i["best"], -i["pixels"])):
            card = CopyCard(item, self.thumbs.get(item["path"]))
            card.set_zoom(self.zoom_level, self._card_room())
            card.clicked.connect(self._open)
            card.context_requested.connect(self._card_menu)
            self.cards.append(card)
            self.compare_row.addWidget(card)

    def _open(self, path):
        try:
            open_path(path)
        except OSError as exc:
            dialogs.error("Couldn't open the video", str(exc))

    # ---------- what's selected and ticked ----------
    def _selection(self):
        row = self.tree.currentItem()
        if row is None:
            return None, None
        group = self.by_key.get(row.data(0, ROW_GROUP))
        if group is None:
            return None, None
        if row.parent() is None:
            return group, None
        path = row.data(0, ROW_PATH)
        return group, next((i for i in group["items"] if i["path"] == path), None)

    def _targets(self):
        """(ticked group keys, ticked copies not in those groups); with nothing ticked, the selected row."""
        keys, files = set(), []
        ticked = self.ticking.ticked() if hasattr(self, "ticking") else []
        for row in ticked:
            if row.parent() is None:
                keys.add(row.data(0, ROW_GROUP))
        for row in ticked:
            if row.parent() is not None and row.data(0, ROW_GROUP) not in keys:
                files.append(row.data(0, ROW_PATH))
        if not ticked and hasattr(self, "tree"):
            group, item = self._selection()
            if item is not None:
                files.append(item["path"])
            elif group is not None:
                keys.add(group["key"])
        return keys, files

    def _group_of(self, path):
        return next((g for g in self.groups if any(de._normal(i["path"]) == de._normal(path) for i in g["items"])),
                    None)

    def _mark_best(self, path):
        group = self._group_of(path)
        if group is None:
            return
        for item in group["items"]:
            item["best"] = de._normal(item["path"]) == de._normal(path)
        self.app.log(f"Made {Path(path).name} the best copy.")
        de.save_results(self.mode.value(), self.groups)
        self._render()

    def _mark_selected_best(self):
        _g, item = self._selection()
        if item:
            self._mark_best(item["path"])

    def _tree_menu(self, pos):
        row = self.tree.itemAt(pos)
        if row is not None:
            self.tree.setCurrentItem(row)
        group, item = self._selection()
        menu = QMenu(self)
        if item is not None:
            menu.addAction("Open", lambda: self._open(item["path"]))
            menu.addAction("Show in Explorer", lambda: show_in_explorer(item["path"]))
            if not item["best"]:
                menu.addAction("Make this the best copy", lambda: self._mark_best(item["path"]))
            menu.addAction("Keep this copy…", self._keep_selected)
            menu.addAction("Send to the Recycle Bin…", lambda: self._recycle([item["path"]]))
        elif group is not None:
            menu.addAction("Keep the best copy…", self._keep_selected)
            menu.addAction("Ignore this group", self._ignore_group)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _card_menu(self, path, global_pos):
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open(path))
        menu.addAction("Show in Explorer", lambda: show_in_explorer(path))
        group = self._group_of(path)
        item = next((i for i in group["items"] if de._normal(i["path"]) == de._normal(path)), None) if group else None
        if item is not None and not item["best"]:
            menu.addAction("Make this the best copy", lambda: self._mark_best(path))
        menu.addAction("Send to the Recycle Bin…", lambda: self._recycle([path]))
        menu.exec(global_pos)

    # ---------- acting ----------
    def _recycle_targets(self):
        keys, files = self._targets()
        for key in keys:
            group = self.by_key.get(key)
            if group:
                files += [i["path"] for i in group["items"] if not i["best"] and i["path"] not in files]
        if not files:
            dialogs.info("Tick the copies to recycle", "Tick copies with their tick box or Ctrl+click, or select "
                         "one. Ticking a group recycles every copy but its best one.", icon_name="info")
            return
        self._recycle(files)

    def _recycle(self, files):
        n = len(files)
        if not dialogs.ask(f"Send {plural(n, 'file')} to the Recycle Bin?",
                           "You can restore them from the Recycle Bin. Every removal is written to the deletions log.",
                           f"Send {plural(n, 'file')} to the Recycle Bin", kind="danger",
                           items=[(Path(f).name, str(Path(f).parent)) for f in files], icon_name="warn"):
            return
        entries = []
        for f in files:
            group = self._group_of(f)
            item = next((i for i in group["items"] if i["path"] == f), None) if group else None
            best = next((i["path"] for i in group["items"] if i["best"]), "") if group else ""
            entries.append((f, best if best != f else "", item["match"] if item else "",
                            item["similarity"] if item else 0))
        self.app.start(jobs.Job(f"Sending {plural(n, 'file')} to the Recycle Bin", self._recycle_job, entries,
                                short="Recycling", done=self._removed))

    def _recycle_job(self, entries, log, progress):
        try:
            sent = de.recycle_files(entries, log, progress)
        except fileops.RecycleError as exc:
            log(f"ERROR: {exc}")
            raise
        return {"summary": f"{plural(len(sent), 'file')} sent to the Recycle Bin", "removed": sent}

    def _keep_selected(self):
        group, item = self._selection()
        if group is None:
            return
        keep = item["path"] if item else next(i["path"] for i in group["items"] if i["best"])
        entries = de.keep_one_entries(group, keep)
        n = len(entries)
        if not dialogs.ask(f"Keep {Path(keep).name} and send {plural(n, 'other copy', 'other copies')} to the "
                           "Recycle Bin?", f"Kept: {keep}. The others can be restored from the Recycle Bin, and "
                           "every removal is written to the deletions log.",
                           f"Send {plural(n, 'file')} to the Recycle Bin", kind="danger",
                           items=[(Path(e[0]).name, str(Path(e[0]).parent)) for e in entries], icon_name="warn"):
            return
        self.app.start(jobs.Job(f"Keeping {Path(keep).name}", self._recycle_job, entries, short="Recycling",
                                done=self._removed))

    def _removed(self, job):
        result = job.result if isinstance(job.result, dict) else {}
        removed = result.get("removed", [])
        if removed:
            self._apply_removed(removed)
            self.app.toast(f"Sent {plural(len(removed), 'file')} to the Recycle Bin.", "ok")

    def _move_targets(self):
        keys, files = self._targets()
        if not keys and not files:
            dialogs.info("Tick the groups or copies to move", "Tick a group to move all its copies into their own "
                         "folder, or tick single copies.", icon_name="info")
            return
        target = QFileDialog.getExistingDirectory(self, "Move duplicates to")
        if not target:
            return
        ops = de.plan_moves(self.groups, keys, files, target)
        chosen = dialogs.review_moves("Move these duplicates?", ops)
        if not chosen:
            return
        self.app.start(jobs.Job("Moving duplicates", self._move_job, chosen, short="Moving", done=self._moved))

    def _move_job(self, ops, log, progress):
        moved = de.execute_moves(ops, log, progress)
        return {"summary": f"{plural(len(moved), 'file')} moved, {len(ops) - len(moved)} copied",
                "moved": moved, "next": ("Show the log of moves", lambda: (self.app.toggle_drawer(True),
                                                                           self.app.drawer.show_moves()))}

    def _moved(self, job):
        result = job.result if isinstance(job.result, dict) else {}
        if result.get("moved"):
            self._apply_removed(result["moved"])
            self.app.toast("Moved. Ctrl+Z puts them back.", "ok")

    def after_undo(self, entry):
        if entry.get("tool") == "Duplicate videos":
            self.app.toast("The files are back. Scan again to see them in groups.", "info")

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
        de.save_results(self.mode.value(), kept)

    def _open_selected(self):
        _g, item = self._selection()
        if item:
            self._open(item["path"])

    def _show_selected(self):
        _g, item = self._selection()
        if item:
            show_in_explorer(item["path"])

    def _open_offset(self):
        _g, item = self._selection()
        if not item:
            return
        self.app.log(f"{item['name']} is a clip that starts at {de.format_seconds(item['offset'])} in the longer "
                     "video. Opening it; jump to that time in your player.")
        self._open(item["path"])

    def _ignore_group(self):
        keys, _files = self._targets()
        group, _item = self._selection()
        keys = keys or ({group["key"]} if group else set())
        if not keys:
            return
        ignored = settings.load().get("dup_ignored", [])
        for k in keys:
            if k not in ignored:
                ignored.append(k)
        settings.save({"dup_ignored": ignored})
        self.groups = [g for g in self.groups if g["key"] not in keys]
        self.by_key = {g["key"]: g for g in self.groups}
        de.save_results(self.mode.value(), self.groups)
        self._render()
        self.app.toast(f"Ignored {plural(len(keys), 'group')}. They won't come back in future scans. Settings › "
                       "Reset can bring them back.", "info")

    # ---------- keys ----------
    def tick_all(self):
        self.ticking.tick_all(not all(r.checkState(0) == Qt.Checked for r in self.ticking._visible_items()))

    def step(self, delta):
        groups = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        if not groups:
            return False
        cur = self.tree.currentItem()
        top = cur.parent() or cur if cur else None
        i = groups.index(top) if top in groups else -1
        if delta == float("-inf"):
            i = 0
        elif delta == float("inf"):
            i = len(groups) - 1
        else:
            i = max(0, min(len(groups) - 1, i + int(delta)))
        self.tree.setCurrentItem(groups[i])
        return True

    def space(self):
        row = self.tree.currentItem()
        if row is None:
            return False
        row.setCheckState(0, Qt.Unchecked if row.checkState(0) == Qt.Checked else Qt.Checked)
        return True

    def closing(self):
        preview.hover().stop()

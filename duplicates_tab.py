"""Duplicate videos page: a front end for the vdf-cli engine (see duplicates_engine.py)."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QListWidget,
                               QMessageBox, QSlider, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

import duplicates_engine as de
import icons
import settings
import theme
from widgets import Page, button, card, folder_row, label, line_edit, muted, remember

ROW_PATH = Qt.UserRole
ROW_GROUP = Qt.UserRole + 1
VIDEO_FILTER = "Videos (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.3gp);;All files (*.*)"

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
        saved = settings.load()
        opts = saved.get("dup_options", {})

        # ----- mode -----
        self.mode = QComboBox()
        self.mode.addItem("Find duplicates in a folder", "folder")
        self.mode.addItem("Check file(s) against a library folder", "library")
        self.mode.setCurrentIndex(0 if opts.get("mode", "folder") == "folder" else 1)
        self.mode.currentIndexChanged.connect(self._show_mode)

        self.folder = line_edit(saved.get("dup_last_folder", ""), placeholder="Choose the folder to search")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(opts.get("recursive", True))

        self.files = QListWidget()
        self.files.setMinimumHeight(theme.px(90))
        self.files.setSelectionMode(QListWidget.ExtendedSelection)
        for path in saved.get("dup_last_files", []):
            if Path(path).exists():
                self.files.addItem(path)
        self.library = line_edit(saved.get("dup_last_library", ""), placeholder="Choose the library folder")

        mode_card = card()
        mode_grid = QGridLayout(mode_card)
        self._pad(mode_grid)
        mode_grid.setColumnStretch(1, 1)
        mode_grid.addWidget(muted("Mode"), 0, 0)
        mode_grid.addWidget(self.mode, 0, 1, 1, 2)

        self.panel_a = QWidget()
        a = QGridLayout(self.panel_a)
        a.setContentsMargins(0, 0, 0, 0)
        a.setColumnStretch(1, 1)
        folder_row(a, 0, "Folder", self.folder, "Choose the folder to search")
        a.addWidget(self.recursive, 1, 1, 1, 2)
        self.panel_b = QWidget()
        b = QGridLayout(self.panel_b)
        b.setContentsMargins(0, 0, 0, 0)
        b.setColumnStretch(1, 1)
        add = button("Add files...")
        add.clicked.connect(self._add_files)
        remove = button("Remove selected")
        remove.clicked.connect(self._remove_files)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        b.addWidget(muted("Videos to check"), 0, 0, alignment=Qt.AlignTop)
        b.addWidget(self.files, 0, 1, 1, 2)
        b.addLayout(row, 1, 1, 1, 2)
        folder_row(b, 2, "Library", self.library, "Choose the library folder to check against")
        mode_grid.addWidget(self.panel_a, 1, 0, 1, 3)
        mode_grid.addWidget(self.panel_b, 2, 0, 1, 3)
        self._show_mode(self.mode.currentIndex())
        self.body.addWidget(mode_card)

        # ----- options -----
        self.percent = QSlider(Qt.Horizontal)
        self.percent.setRange(50, 100)
        self.percent.setValue(int(opts.get("percent", 95)))
        self.percent_label = muted("")
        self.percent.valueChanged.connect(lambda v: self.percent_label.setText(f"{v}%"))
        self.percent_label.setText(f"{self.percent.value()}%")

        self.audio = QCheckBox("Find partial clips by audio (off by default)")
        self.audio.setChecked(opts.get("audio", False))
        self.audio_ratio = self._percent_spin(opts.get("audio_ratio", 10), 1, 100)
        self.audio_sim = self._percent_spin(opts.get("audio_similarity", 80), 1, 100)

        self.visual = QCheckBox("Find partial clips by visual AI (off by default)")
        self.visual.setChecked(opts.get("visual", False))
        self.visual_hit = self._percent_spin(opts.get("visual_hit", 89), 70, 99)

        opt_card = card()
        g = QGridLayout(opt_card)
        self._pad(g)
        g.setColumnStretch(2, 1)
        g.addWidget(label("Similarity", "body"), 0, 0)
        g.addWidget(self.percent, 0, 1)
        g.addWidget(self.percent_label, 0, 2, alignment=Qt.AlignLeft)
        g.addWidget(muted(EXPLAIN_EXACT, wrap=True), 1, 0, 1, 3)
        g.addWidget(self.audio, 2, 0, 1, 3)
        g.addWidget(self._indented(muted("Minimum clip length, as a share of the longer video"), self.audio_ratio),
                    3, 0, 1, 3)
        g.addWidget(self._indented(muted("Minimum audio match"), self.audio_sim), 4, 0, 1, 3)
        g.addWidget(muted(EXPLAIN_AUDIO, wrap=True), 5, 0, 1, 3)
        g.addWidget(self.visual, 6, 0, 1, 3)
        g.addWidget(self._indented(muted("Per-frame match needed"), self.visual_hit), 7, 0, 1, 3)
        g.addWidget(muted(EXPLAIN_VISUAL, wrap=True), 8, 0, 1, 3)
        self.body.addWidget(opt_card)

        # ----- engine -----
        self.engine_label = muted("")
        self.ffmpeg_label = muted("")
        self.install_btn = button("Install engine", "primary", icons.icon("move", "#ffffff", 18))
        self.install_btn.clicked.connect(self._install_engine)
        self.update_btn = button("Check for engine update")
        self.update_btn.clicked.connect(self._check_update)
        self.ffmpeg_btn = button("Download FFmpeg")
        self.ffmpeg_btn.clicked.connect(self._install_ffmpeg)
        eng = card()
        eg = QGridLayout(eng)
        self._pad(eg)
        eg.setColumnStretch(0, 1)
        eg.addWidget(self.engine_label, 0, 0)
        eg.addWidget(self.install_btn, 0, 1)
        eg.addWidget(self.update_btn, 0, 2)
        eg.addWidget(self.ffmpeg_label, 1, 0)
        eg.addWidget(self.ffmpeg_btn, 1, 1, 1, 2)
        eg.addWidget(muted("The detection engine (vdf-cli, from 0x90d/videoduplicatefinder) is downloaded "
                           "when you install it, into the app data folder. It is not part of this app.", wrap=True),
                     2, 0, 1, 3)
        self.body.addWidget(eng)

        # ----- actions -----
        self.scan_btn = button("Scan", "primary", icons.icon("search", "#ffffff", 18))
        self.scan_btn.clicked.connect(self._scan)
        self.cancel_btn = button("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        actions = QHBoxLayout()
        actions.setSpacing(theme.px(8))
        actions.addWidget(self.scan_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        self.body.addLayout(actions)

        # ----- results -----
        self.filter = QComboBox()
        for text, value in (("All match types", None), ("Exact", "exact"), ("Near", "near"),
                            ("Partial clip (audio)", "partial_audio"),
                            ("Partial clip (visual AI)", "partial_visual")):
            self.filter.addItem(text, value)
        self.filter.currentIndexChanged.connect(lambda _i: self._render())
        self.sort = QComboBox()
        self.sort.addItem("Largest first", "size")
        self.sort.addItem("Most similar first", "similarity")
        self.sort.currentIndexChanged.connect(lambda _i: self._render())
        self.summary = muted("No scan yet.", wrap=True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "File", "Folder", "Size", "Resolution", "Duration", "Bitrate", "Match",
                                   "Similarity", "Clip starts", "Best"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setIconSize(QSize(theme.px(96), theme.px(54)))
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.header().setMinimumSectionSize(theme.px(60))
        for i, width in enumerate((110, 230, 260, 80, 100, 80, 90, 170, 90, 90, 60)):
            self.tree.setColumnWidth(i, theme.px(width))
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda item, _c: self._open_selected())
        remember("dup_tree", self.tree, header=True)

        res = card()
        rv = QVBoxLayout(res)
        self._pad(rv)
        top = QHBoxLayout()
        top.setSpacing(theme.px(8))
        top.addWidget(muted("Show"))
        top.addWidget(self.filter)
        top.addWidget(muted("Sort by"))
        top.addWidget(self.sort)
        top.addSpacing(theme.px(12))
        top.addWidget(self.summary, 1)
        rv.addLayout(top)
        rv.addWidget(self.tree, 1)

        self.btn_open = button("Open")
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_show = button("Show in Explorer")
        self.btn_show.clicked.connect(self._show_selected)
        self.btn_offset = button("Open at offset")
        self.btn_offset.clicked.connect(self._open_offset)
        self.btn_keep = button("Keep this one", "primary")
        self.btn_keep.clicked.connect(self._keep_selected)
        self.btn_ignore = button("Ignore group")
        self.btn_ignore.clicked.connect(self._ignore_group)
        file_bar = QHBoxLayout()
        file_bar.setSpacing(theme.px(8))
        file_bar.addWidget(muted("Selected file:"))
        for widget in (self.btn_open, self.btn_show, self.btn_offset):
            file_bar.addWidget(widget)
        file_bar.addStretch(1)
        group_bar = QHBoxLayout()
        group_bar.setSpacing(theme.px(8))
        group_bar.addWidget(muted("Selected group:"))
        for widget in (self.btn_keep, self.btn_ignore):
            group_bar.addWidget(widget)
        group_bar.addStretch(1)
        rv.addLayout(file_bar)
        rv.addLayout(group_bar)
        self.body.addWidget(res, 1)

        self._refresh_engine_status()
        self._update_buttons()

    # ---------- small helpers ----------
    def _show_mode(self, index):
        self.panel_a.setVisible(index == 0)
        self.panel_b.setVisible(index == 1)

    def _pad(self, layout):
        layout.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        if isinstance(layout, QGridLayout):
            layout.setHorizontalSpacing(theme.px(10))
            layout.setVerticalSpacing(theme.px(8))
        else:
            layout.setSpacing(theme.px(8))

    def _percent_spin(self, value, low, high):
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSuffix("%")
        spin.setValue(int(value))
        return spin

    def _indented(self, text_widget, spin):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(theme.px(24), 0, 0, 0)
        h.addWidget(text_widget)
        h.addStretch(1)
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

    # ---------- results view ----------
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
            header.setFirstColumnSpanned(True)
            visible = [i for i in group["items"] if flt is None or i["match"] == flt or i["best"]]
            header.setText(0, f"Group {number}: {len(group['items'])} copies, "
                              f"{de.MATCH_LABELS.get(de.group_match(group), '')}")
            header.setData(0, ROW_GROUP, group["key"])
            header.setExpanded(True)
            for item in sorted(visible, key=lambda i: (not i["best"], -i["pixels"])):
                copies += 1
                row = QTreeWidgetItem(header)
                pix = self.thumbs.get(item["path"])
                if pix is not None:
                    row.setIcon(0, self._icon(pix))
                row.setText(1, item["name"] + (" (picked file)" if item.get("picked") else ""))
                row.setText(2, item["folder"])
                row.setText(3, _size_text(item["size"]))
                row.setText(4, item["resolution"])
                row.setText(5, de.format_seconds(item["duration"]))
                row.setText(6, f"{item['bitrate']:.0f} kb/s" if item["bitrate"] else "")
                row.setText(7, de.MATCH_LABELS.get(item["match"], item["match"]))
                row.setText(8, f"{item['similarity']:.1f}%")
                row.setText(9, de.format_seconds(item["offset"]) if item["offset"] else "")
                row.setText(10, "Best" if item["best"] else "")
                row.setData(1, ROW_PATH, item["path"])
                row.setData(0, ROW_GROUP, group["key"])
        self.summary.setText(f"{len(shown)} group(s) shown, {copies} file(s)."
                             if self.groups else "No duplicates in the last scan.")
        self._update_buttons()
        self._request_thumbs(shown)

    def _icon(self, qimage):
        return QIcon(QPixmap.fromImage(qimage))

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
                qimg = None  # no thumbnail, the row still shows
            self.app.on_main(lambda p=path, q=qimg: self._thumb_ready(p, q))

    def _thumb_ready(self, path, qimg):
        self.thumbs_busy.discard(path)
        if qimg is None:
            return
        self.thumbs[path] = qimg
        icon = self._icon(qimg)
        root = self.tree.invisibleRootItem()
        for g in range(root.childCount()):
            header = root.child(g)
            for c in range(header.childCount()):
                row = header.child(c)
                if row.data(1, ROW_PATH) == path:
                    row.setIcon(0, icon)

    # ---------- selection and actions ----------
    def _selection(self):
        """(group, item or None) for the row that is selected, or (None, None)."""
        row = self.tree.currentItem()
        if row is None:
            return None, None
        key = row.data(0, ROW_GROUP)
        group = self.by_key.get(key)
        if group is None:
            return None, None
        if row.parent() is None:
            return group, None
        path = row.data(1, ROW_PATH)
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

    def _open_selected(self):
        _group, item = self._selection()
        if item:
            try:
                _open_path(item["path"])
            except OSError as exc:
                self.app.log(f"ERROR: could not open the file: {exc}")

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
        self._open_selected()

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


def _size_text(n):
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"

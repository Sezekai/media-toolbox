"""Media Toolbox: a sidebar app with one page per tool."""
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor

from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QMenu, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import folder_tools
import icons
import settings
import silent_videos
import theme
import webp_convert
from duplicates_tab import DuplicatesPage
from gif_tab import GifTab
from widgets import (Bridge, ElidedLabel, FIELD_LABEL_W, FolderChecklist, Page, add_folder, button, divider,
                     field_label, label, line_edit, make_tree, remember, reset_remembered, results_bar,
                     results_panel, tool_row, toolbar)

ITEM_PATH = Qt.UserRole


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


class SilentPage(Page):
    title = "Silent videos"
    subtitle = "Find videos with no audio, select the ones you want, then move them to another folder."

    def build(self):
        self.folder = line_edit(placeholder="Choose the video folder")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.loud = QCheckBox("Also check audio level (slower)")
        self.threshold = line_edit("-60", width=56)
        self.threshold.setToolTip("When the audio level is checked, videos quieter than this count as silent")

        bar, rows = toolbar()
        top = tool_row()
        add_folder(top, "Video folder", self.folder, "Choose the video folder")
        scan = button("Scan", "primary", icons.icon("search", theme.ON_ACCENT, 16))
        scan.clicked.connect(self.scan)
        top.addWidget(divider())
        top.addWidget(scan)
        rows.addLayout(top)
        opts = tool_row()
        opts.addWidget(field_label("Options"))
        opts.addWidget(self.recursive)
        opts.addSpacing(8)
        opts.addWidget(self.loud)
        opts.addSpacing(8)
        opts.addWidget(label("Threshold", "muted"))
        opts.addWidget(self.threshold)
        opts.addWidget(label("dB", "muted"))
        opts.addStretch(1)
        rows.addLayout(opts)
        self.body.addWidget(bar)

        panel, pv = results_panel()
        self.summary = ElidedLabel("Choose a folder and click Scan.")
        select = button("Select all")
        select.clicked.connect(lambda: self.tree.selectAll())
        move = button("Move selected", "primary", icons.icon("move", theme.ON_ACCENT, 16))
        move.clicked.connect(self.move_selected)
        pv.addLayout(results_bar(self.summary, select, move))
        self.tree = make_tree(("File", "Reason"), (400, 280))
        remember("silent_tree", self.tree, header=True)
        pv.addWidget(self.tree, 1)
        self.body.addWidget(panel, 1)

    def scan(self):
        folder = self.folder.text().strip()
        if not Path(folder).is_dir():
            QMessageBox.critical(self, "Folder not found", "Choose a valid video folder.")
            return
        try:
            threshold = float(self.threshold.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid threshold", "Enter a number such as -60.")
            return
        self.app.run_background(self._scan_worker, folder, self.recursive.isChecked(),
                                self.loud.isChecked(), threshold)

    def _scan_worker(self, folder, recursive, loud, threshold, log, progress):
        silent = silent_videos.scan_folder(folder, recursive, loud, threshold, log=log, progress=progress)
        self.app.on_main(lambda: self._show_results(silent))

    def _show_results(self, silent):
        self.tree.clear()
        for path, reason in silent:
            row = QTreeWidgetItem([str(path), reason])
            row.setData(0, ITEM_PATH, str(path))
            self.tree.addTopLevelItem(row)
        self.summary.setText(f"{len(silent)} silent video(s). Select the ones to move.")

    def move_selected(self):
        rows = self.tree.selectedItems()
        if not rows:
            QMessageBox.information(self, "Nothing selected",
                                    "Select one or more videos in the list first (or click Select all).")
            return
        dest = QFileDialog.getExistingDirectory(self, "Move selected videos to...")
        if not dest:
            return
        paths = [Path(r.data(0, ITEM_PATH)) for r in rows]
        self.app.run_background(self._move_worker, paths, dest)

    def _move_worker(self, paths, dest, log, progress):
        moved = silent_videos.move_files(paths, dest, log=log, progress=progress)
        moved_ids = {str(p) for p in moved}
        self.app.on_main(lambda: self._remove_rows(moved_ids))

    def _remove_rows(self, moved_ids):
        for i in reversed(range(self.tree.topLevelItemCount())):
            if self.tree.topLevelItem(i).data(0, ITEM_PATH) in moved_ids:
                self.tree.takeTopLevelItem(i)
        self.summary.setText(f"{self.tree.topLevelItemCount()} silent video(s) remaining")


class ZipPage(Page):
    title = "Zip subfolders"
    subtitle = "Each ticked subfolder becomes its own zip file, named after the folder."

    def build(self):
        self.source = line_edit(placeholder="Choose a parent folder")
        self.dest = line_edit(placeholder="Empty = save the zips beside the folders")
        bar, rows = toolbar()
        top = tool_row()
        add_folder(top, "Parent folder", self.source, "Choose the parent folder", on_change=self.refresh)
        self.source.editingFinished.connect(self.refresh)
        run = button("Zip ticked folders", "primary", icons.icon("zip", theme.ON_ACCENT, 16))
        run.clicked.connect(self.run)
        top.addWidget(divider())
        top.addWidget(run)
        rows.addLayout(top)
        second = tool_row()
        add_folder(second, "Save zips to", self.dest, "Choose where to save the zips")
        rows.addLayout(second)
        self.body.addWidget(bar)

        panel, pv = results_panel()
        self.checklist = FolderChecklist("Folders in this folder", recursive=False, key="zip_folders")
        self.checklist.clear("Choose a parent folder to see its folders.")
        pv.addWidget(self.checklist, 1)
        self.body.addWidget(panel, 1)

    def refresh(self):
        path = self.source.text().strip()
        if Path(path).is_dir():
            self.checklist.load(Path(path))
        else:
            self.checklist.clear("Choose a parent folder to see its folders.")

    def run(self):
        src = self.source.text().strip()
        dst = self.dest.text().strip() or None
        if not Path(src).is_dir():
            QMessageBox.critical(self, "Folder not found", "Choose a valid parent folder.")
            return
        names = self.checklist.checked_names()
        if not names:
            QMessageBox.information(self, "Nothing ticked", "Tick at least one folder to zip.")
            return
        self.app.run_background(folder_tools.zip_subfolders, src, dst, only=names)


class WebpPage(Page):
    title = "WebP to JPG"
    subtitle = "Pick a folder to see its WebP images before converting. Each JPG is saved beside its original."
    QUALITY_STEPS = [100, 95, 90, 85, 80, 75, 70, 60, 50]
    QUALITY_INFO = {
        100: "Maximum. No visible change from the original, but the largest files. Only worth it for archiving or heavy editing.",
        95: "Near-perfect, and very hard to tell from the original. This was the app's setting until now.",
        90: "Excellent. Looks the same to almost everyone, with noticeably smaller files. A good everyday choice.",
        85: "Very good. A slight loss in fine detail and smooth gradients. Fine for photos and art shared online.",
        80: "Good. Files are much smaller, and fine textures can soften when zoomed in.",
        75: "Fair. Good where file size matters. Faint blocky edges can show around sharp lines.",
        70: "Visible artefacts around text and sharp edges. Use when size matters most.",
        60: "Low. Blocky patterns in flat colours and gradients are common.",
        50: "Lowest. Clearly degraded. Only suitable for thumbnails or previews.",
    }

    def build(self):
        self.folder = line_edit(placeholder="Choose a folder")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.toggled.connect(lambda _c: self.scan())
        self.delete_originals = QCheckBox("Recycle originals after converting")
        self.delete_originals.setToolTip("Send the original .webp files to the Recycle Bin once each JPG is saved")
        self.quality = QComboBox()
        self.quality.addItems([f"{q}%" for q in self.QUALITY_STEPS])
        self.quality.setCurrentText("95%")
        self.quality.currentTextChanged.connect(self._quality_changed)
        self.quality.setToolTip("Higher = bigger file, better detail")
        self.rows = []  # (Path, folder shown in the list, size in bytes)

        bar, rows = toolbar()
        top = tool_row()
        add_folder(top, "Folder", self.folder, "Choose the folder", on_change=self.scan)
        scan = button("Scan folder")
        scan.clicked.connect(self.scan)
        top.addWidget(scan)
        convert_all = button("Convert all listed", "primary", icons.icon("image", theme.ON_ACCENT, 16))
        convert_all.clicked.connect(lambda: self.convert(False))
        top.addWidget(divider())
        top.addWidget(convert_all)
        rows.addLayout(top)
        opts = tool_row()
        opts.addWidget(field_label("JPG quality"))
        self.quality.setFixedWidth(90)
        opts.addWidget(self.quality)
        opts.addSpacing(8)
        opts.addWidget(self.recursive)
        opts.addSpacing(8)
        opts.addWidget(self.delete_originals)
        opts.addStretch(1)
        rows.addLayout(opts)
        self.quality_info = ElidedLabel(self.QUALITY_INFO[95] + "  JPG can't store transparency (it becomes white), "
                                  "animated WebP keeps only its first frame, and metadata is not kept.",
                                  "caption")
        self.quality_info.setContentsMargins(FIELD_LABEL_W + 8, 0, 0, 0)
        rows.addWidget(self.quality_info)
        self.body.addWidget(bar)

        panel, pv = results_panel()
        self.summary = ElidedLabel("Choose a folder to see its WebP files.")
        convert_sel = button("Convert selected")
        convert_sel.clicked.connect(lambda: self.convert(True))
        pv.addLayout(results_bar(self.summary, convert_sel))
        self.tree = make_tree(("File", "Folder", "Size"), (300, 360, 90))
        remember("webp_tree", self.tree, header=True)
        pv.addWidget(self.tree, 1)
        self.body.addWidget(panel, 1)

    def _quality_changed(self, choice):
        self.quality_info.setText(self.QUALITY_INFO[int(choice.rstrip("%"))] + "  JPG can't store transparency "
                                  "(it becomes white), animated WebP keeps only its first frame, and metadata "
                                  "is not kept.")

    def scan(self):
        folder = self.folder.text().strip()
        if not Path(folder).is_dir():
            self._show([])
            self.summary.setText("Choose a folder to see its WebP files.")
            return
        recursive = self.recursive.isChecked()
        self.summary.setText("Scanning...")
        root = Path(folder)

        def worker():
            rows = []
            for p in webp_convert.find_webp(root, recursive):
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                rel = p.parent.relative_to(root)
                where = "(top folder)" if str(rel) == "." else str(rel)
                rows.append((p, where, size))
            self.app.on_main(lambda: self._show(rows))
            self.app.log(f"Scan finished: {len(rows)} WebP file(s) in {folder}")

        threading.Thread(target=worker, daemon=True).start()

    def _show(self, rows):
        self.rows = rows
        self.tree.clear()
        for p, where, size in rows:
            row = QTreeWidgetItem([p.name, where, fmt_size(size)])
            row.setData(0, ITEM_PATH, str(p))
            self.tree.addTopLevelItem(row)
        if not rows:
            self.summary.setText("No WebP files found in this folder.")
            return
        total = sum(size for _, _, size in rows)
        folders = len({where for _, where, _ in rows})
        self.summary.setText(f"{len(rows)} WebP file(s) in {folders} folder(s), {fmt_size(total)} in total")

    def convert(self, selected_only):
        if not self.rows:
            QMessageBox.information(self, "No files", "Choose a folder with WebP files first.")
            return
        if selected_only:
            rows = self.tree.selectedItems()
            if not rows:
                QMessageBox.information(self, "Nothing selected", "Select one or more files in the list first.")
                return
            paths = [Path(r.data(0, ITEM_PATH)) for r in rows]
        else:
            paths = [p for p, _, _ in self.rows]
        quality = int(self.quality.currentText().rstrip("%"))
        delete = self.delete_originals.isChecked()
        if delete and QMessageBox.question(
                self, "Confirm", f"The original .webp files of the {len(paths)} selected file(s) will be sent to "
                                 "the Recycle Bin after converting. Continue?") != QMessageBox.Yes:
            return
        self.app.run_background(webp_convert.convert_files, paths, quality, delete)


class CopyPage(Page):
    title = "Copy folder structure"
    subtitle = "Recreate a folder's sub-folders in another location, without copying any files. Untick any to leave them out."

    def build(self):
        self.source = line_edit(placeholder="Choose the folder to copy")
        self.dest = line_edit(placeholder="Choose the destination")
        bar, rows = toolbar()
        top = tool_row()
        add_folder(top, "Copy from", self.source, "Choose the folder to copy", on_change=self.refresh)
        self.source.editingFinished.connect(self.refresh)
        run = button("Copy folder structure", "primary", icons.icon("copy_folder", theme.ON_ACCENT, 16))
        run.clicked.connect(self.run)
        top.addWidget(divider())
        top.addWidget(run)
        rows.addLayout(top)
        second = tool_row()
        add_folder(second, "Copy into", self.dest, "Choose the destination")
        rows.addLayout(second)
        self.body.addWidget(bar)

        panel, pv = results_panel()
        self.checklist = FolderChecklist("Folders to copy", recursive=True, key="copy_folders")
        self.checklist.clear("Choose a folder to see its sub-folders.")
        pv.addWidget(self.checklist, 1)
        self.body.addWidget(panel, 1)

    def refresh(self):
        path = self.source.text().strip()
        if Path(path).is_dir():
            self.checklist.load(Path(path))
        else:
            self.checklist.clear("Choose a folder to see its sub-folders.")

    def run(self):
        src = self.source.text().strip()
        dst = self.dest.text().strip()
        if not Path(src).is_dir() or not dst:
            QMessageBox.critical(self, "Missing input", "Choose a source folder and a destination.")
            return
        self.app.run_background(folder_tools.copy_folder_structure, src, dst,
                                skip=self.checklist.unchecked_paths())


SIDEBAR_EXPANDED = 176  # with the tool names
SIDEBAR_COLLAPSED = 44  # icons only

NAV = [
    ("silent", "Silent videos", "silent"),
    ("gif", "GIF maker", "gif"),
    ("dupes", "Duplicate videos", "duplicate"),
    ("zip", "Zip subfolders", "zip"),
    ("webp", "WebP to JPG", "image"),
    ("copy", "Copy folder structure", "copy_folder"),
]
PAGES = {
    "silent": SilentPage,
    "gif": GifTab,
    "dupes": DuplicatesPage,
    "zip": ZipPage,
    "webp": WebpPage,
    "copy": CopyPage,
}


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Toolbox")
        self.resize(1280, 820)
        self.bridge = Bridge()
        self.current_key = "silent"
        self.nav = {}
        self.pages = {}
        self._build()

    # ---------- layout ----------
    def _build(self):
        """Sidebar on the left; the tool fills the rest; a status bar along the bottom with the log above it."""
        reset_remembered()
        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._rail())

        self.stack = QStackedWidget()
        for key, cls in PAGES.items():
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(12, 10, 12, 10)
            page = cls(self)
            hl.addWidget(page)
            self.stack.addWidget(holder)
            self.pages[key] = page

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(4)
        self.split.addWidget(self.stack)
        self.split.addWidget(self._log_panel())
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([620, 170])
        remember("main_split2", self.split)
        right.addWidget(self.split, 1)
        right.addWidget(self._status_bar())
        h.addLayout(right, 1)

        self.setCentralWidget(root)
        root.setFocusPolicy(Qt.ClickFocus)
        root.setFocus()  # start with nothing highlighted
        self._set_log_open(settings.load().get("log_open", False), save=False)
        self.show_page(self.current_key)
        self._fit_window()

    def _rail(self):
        """The sidebar: the tools with their names, or just their icons when collapsed.
        At the bottom: the accent colour menu and the collapse / expand button."""
        self.expanded = bool(settings.load().get("sidebar_expanded", True))
        rail = QFrame()
        rail.setObjectName("rail")
        self.rail = rail
        v = QVBoxLayout(rail)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(7, 0, 0, 0)
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setToolTip("Media Toolbox")
        self.logo.setFixedSize(18, 28)
        self.brand_name = QLabel("Media Toolbox")
        self.brand_name.setObjectName("brand")
        brand.addWidget(self.logo)
        brand.addWidget(self.brand_name, 1)
        v.addLayout(brand)
        v.addSpacing(8)
        self.nav = {}
        for key, text, icon_name in NAV:
            btn = self._side_button(text)
            btn.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            v.addWidget(btn)
            self.nav[key] = (btn, icon_name)
        v.addStretch(1)
        self.accent_btn = self._side_button("Accent colour")
        self.accent_btn.clicked.connect(self._accent_menu)
        v.addWidget(self.accent_btn)
        self.collapse_btn = self._side_button("Collapse")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        v.addWidget(self.collapse_btn)
        self._apply_sidebar()
        return rail

    def _side_button(self, text):
        btn = QPushButton()
        btn.setProperty("rail", "true")
        btn.setProperty("label", text)
        btn.setAccessibleName(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)  # the active tool shows its state, not a focus ring
        btn.setFixedHeight(32)
        btn.setIconSize(QSize(18, 18))
        return btn

    def _side_buttons(self):
        return [btn for btn, _icon in self.nav.values()] + [self.accent_btn, self.collapse_btn]

    def _apply_sidebar(self):
        width = SIDEBAR_EXPANDED if self.expanded else SIDEBAR_COLLAPSED
        self.rail.setFixedWidth(width)
        self.brand_name.setVisible(self.expanded)
        self.collapse_btn.setProperty("label", "Collapse" if self.expanded else "Expand")
        for btn in self._side_buttons():
            text = btn.property("label")
            btn.setText(f"  {text}" if self.expanded else "")
            btn.setToolTip("" if self.expanded else text)  # names show on hover when collapsed
            btn.setFixedWidth(width - 12)
        self._refresh_side_icons()
        self._fit_window()

    def _toggle_sidebar(self):
        self.expanded = not self.expanded
        settings.save({"sidebar_expanded": self.expanded})
        self._apply_sidebar()

    def _refresh_side_icons(self):
        self.logo.setPixmap(icons.icon("logo", theme.ACCENT, 18).pixmap(18, 18))
        for k, (btn, icon_name) in self.nav.items():
            active = k == self.current_key
            btn.setIcon(icons.icon(icon_name, theme.ACCENT if active else theme.MUTED, 18))
        self.accent_btn.setIcon(icons.swatch(theme.ACCENT, 18))
        self.collapse_btn.setIcon(icons.icon("collapse" if self.expanded else "expand", theme.MUTED, 18))

    # ---------- accent colour ----------
    def _accent_menu(self):
        menu = QMenu(self)
        current = theme.ACCENT.lower()
        for name, colour in theme.ACCENT_PRESETS:
            action = menu.addAction(icons.swatch(colour, 16), name)
            action.setCheckable(True)
            action.setChecked(colour.lower() == current)
            action.triggered.connect(lambda _c=False, c=colour: self.set_accent(c))
        menu.addSeparator()
        custom = menu.addAction("Custom colour...")
        custom.triggered.connect(self._custom_accent)
        menu.exec(self.accent_btn.mapToGlobal(self.accent_btn.rect().topRight()))

    def _custom_accent(self):
        chosen = QColorDialog.getColor(QColor(theme.ACCENT), self, "Accent colour")
        if chosen.isValid():
            self.set_accent(chosen.name())

    def set_accent(self, colour):
        """Use a new accent colour straight away, and remember it."""
        theme.set_accent(colour)
        settings.save({"accent": theme.ACCENT})
        theme.apply(QApplication.instance())
        self._refresh_side_icons()
        for page in self.pages.values():
            page.update()

    # ---------- window size ----------
    def _fit_window(self):
        """The smallest window in which every page fits without sideways scrolling or squeezing."""
        central = self.centralWidget()
        if central is None:
            return  # still being built
        central.layout().activate()
        hint = central.minimumSizeHint()  # the largest page, the sidebar and the status bar
        self.setMinimumSize(hint.width(), max(hint.height(), 560))

    def _status_bar(self):
        """What is running, how far along it is, and the button that opens the log."""
        bar = QFrame()
        bar.setObjectName("statusbar")
        h = QHBoxLayout(bar)
        bar.setFixedHeight(36)
        h.setContentsMargins(14, 0, 8, 0)
        h.setSpacing(12)
        self.status = ElidedLabel("Ready")
        h.addWidget(self.status, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(240)
        h.addWidget(self.bar)
        self.log_toggle = button("Log", icon=icons.icon("log", theme.MUTED, 16))
        self.log_toggle.setCheckable(True)
        self.log_toggle.setToolTip("Show or hide the log of everything the tools have done")
        self.log_toggle.toggled.connect(lambda on: self._set_log_open(on))
        h.addWidget(self.log_toggle)
        return bar

    def _log_panel(self):
        self.log_panel = QFrame()
        self.log_panel.setObjectName("logpanel")
        v = QVBoxLayout(self.log_panel)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label("Log", "heading"))
        head.addStretch(1)
        clear = button("Clear log")
        clear.clicked.connect(self._clear_log)
        head.addWidget(clear)
        v.addLayout(head)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_view.setMaximumBlockCount(5000)
        v.addWidget(self.log_view, 1)
        return self.log_panel

    def _set_log_open(self, on, save=True):
        on = bool(on)
        self.log_panel.setVisible(on)
        if self.log_toggle.isChecked() != on:
            self.log_toggle.blockSignals(True)
            self.log_toggle.setChecked(on)
            self.log_toggle.blockSignals(False)
        if save:
            settings.save({"log_open": on})

    def show_page(self, key):
        self.current_key = key
        self.stack.setCurrentIndex(list(PAGES).index(key))
        for k, (btn, icon_name) in self.nav.items():
            active = k == key
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh_side_icons()

    # ---------- thread-safe updates ----------
    # Background threads never touch the UI directly; they hand callables to the UI thread.
    def log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.bridge.call.emit(lambda: self._append_log(f"{stamp}  {msg}"))

    def on_main(self, fn):
        self.bridge.call.emit(fn)

    def progress(self, done, total, text=""):
        """Show progress for the running job, e.g. progress(3, 10, "Converting")."""
        self.bridge.call.emit(lambda: self._set_progress(done, total, text))

    def _set_progress(self, done, total, text):
        if total:
            self.bar.setValue(round(done / total * 1000))
            self.status.setText(f"{text}: {done} of {total}  ({done * 100 / total:.0f}%)")
        else:
            self.bar.setValue(0)
            self.status.setText(text)

    def _append_log(self, line):
        self.log_view.appendPlainText(line)
        if "ERROR" in line and not self.log_panel.isVisible():
            self._set_log_open(True)  # a failure should never go unseen
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _clear_log(self):
        self.log_view.clear()

    def run_background(self, fn, *args, **kwargs):
        """Run fn in a thread. fn receives log= and progress= callbacks automatically."""
        def worker():
            self.progress(0, 0, "Starting...")
            self.log("Started.")
            try:
                fn(*args, log=self.log, progress=self.progress, **kwargs)
                self.progress(1, 1, "Finished")
                self.log("Finished.")
            except Exception as exc:  # report errors in the log instead of crashing
                self.progress(0, 0, "Failed, see log")
                self.log(f"ERROR: {exc}")
        threading.Thread(target=worker, daemon=True).start()


def main():
    app = QApplication(sys.argv)
    theme.load_fonts()
    theme.set_accent(settings.load().get("accent", theme.DEFAULT_ACCENT))
    theme.apply(app)
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

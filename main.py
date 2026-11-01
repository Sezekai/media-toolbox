"""Media Toolbox: a sidebar app with one page per tool."""
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal

from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QSplitter,
                               QStackedWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import folder_tools
import icons
import settings
import silent_videos
import theme
import webp_convert
from duplicates_tab import DuplicatesPage
from gif_tab import GifTab
from themes import CORNER_STYLES, DEFAULT_THEME, FONT_CHOICES, PALETTES, SIZE_CHOICES
from widgets import (Bridge, FolderChecklist, Page, button, card, folder_row, label, line_edit, make_tree, muted,
                     remember, reset_remembered)

ITEM_PATH = Qt.UserRole


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def _nearest(mapping, value):
    """The label in mapping whose number is closest to value."""
    return min(mapping, key=lambda k: abs(mapping[k] - value))


class SilentPage(Page):
    title = "Silent videos"
    subtitle = "Find videos with no audio, select the ones you want, then move them to another folder."

    def build(self):
        self.folder = line_edit(placeholder="Choose the video folder")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.loud = QCheckBox("Also check audio level (slower)")
        self.threshold = line_edit("-60", width=90)

        setup = card()
        grid = QGridLayout(setup)
        grid.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        grid.setHorizontalSpacing(theme.px(10))
        grid.setVerticalSpacing(theme.px(10))
        grid.setColumnStretch(1, 1)
        folder_row(grid, 0, "Video folder", self.folder, "Choose the video folder")
        options = QHBoxLayout()
        options.addWidget(self.recursive)
        options.addSpacing(theme.px(20))
        options.addWidget(self.loud)
        options.addSpacing(theme.px(20))
        options.addWidget(muted("Threshold (dB)"))
        options.addWidget(self.threshold)
        options.addStretch(1)
        grid.addLayout(options, 1, 0, 1, 3)
        self.body.addWidget(setup)

        actions = QHBoxLayout()
        actions.setSpacing(theme.px(8))
        scan = button("Scan", "primary", icons.icon("search", theme.ON_GREEN, 18))
        scan.clicked.connect(self.scan)
        select = button("Select all")
        select.clicked.connect(lambda: self.tree.selectAll())
        move = button("Move selected", "primary", icons.icon("move", theme.ON_GREEN, 18))
        move.clicked.connect(self.move_selected)
        actions.addWidget(scan)
        actions.addWidget(select)
        actions.addWidget(move)
        self.summary = muted("")
        actions.addSpacing(theme.px(10))
        actions.addWidget(self.summary, 1)
        self.body.addLayout(actions)

        list_card = card()
        layout = QVBoxLayout(list_card)
        layout.setContentsMargins(theme.px(8), theme.px(8), theme.px(8), theme.px(8))
        self.tree = make_tree(("File", "Reason"), (560, 260))
        remember("silent_tree", self.tree, header=True)
        layout.addWidget(self.tree)
        self.body.addWidget(list_card, 1)

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
        setup = card()
        grid = QGridLayout(setup)
        grid.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        grid.setHorizontalSpacing(theme.px(10))
        grid.setVerticalSpacing(theme.px(10))
        grid.setColumnStretch(1, 1)
        folder_row(grid, 0, "Parent folder", self.source, "Choose the parent folder", on_change=self.refresh)
        self.source.editingFinished.connect(self.refresh)
        folder_row(grid, 1, "Save zips to", self.dest, "Choose where to save the zips")
        self.body.addWidget(setup)

        list_card = card()
        lv = QVBoxLayout(list_card)
        lv.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        self.checklist = FolderChecklist("Folders in this folder", recursive=False, key="zip_folders")
        self.checklist.clear("Choose a parent folder to see its folders.")
        lv.addWidget(self.checklist)
        self.body.addWidget(list_card, 1)

        run = button("Zip ticked folders", "primary", icons.icon("zip", theme.ON_GREEN, 18))
        run.clicked.connect(self.run)
        self.body.addWidget(run, 0, Qt.AlignLeft)

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
        self.delete_originals = QCheckBox("Send originals to the Recycle Bin after converting")
        self.quality = QComboBox()
        self.quality.addItems([f"{q}%" for q in self.QUALITY_STEPS])
        self.quality.setCurrentText("95%")
        self.quality.currentTextChanged.connect(self._quality_changed)
        self.rows = []  # (Path, folder shown in the list, size in bytes)

        setup = card()
        grid = QGridLayout(setup)
        grid.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        grid.setHorizontalSpacing(theme.px(10))
        grid.setVerticalSpacing(theme.px(10))
        grid.setColumnStretch(1, 1)
        folder_row(grid, 0, "Folder", self.folder, "Choose the folder", on_change=self.scan)
        options = QHBoxLayout()
        options.addWidget(self.recursive)
        options.addSpacing(theme.px(20))
        options.addWidget(self.delete_originals)
        options.addStretch(1)
        grid.addLayout(options, 1, 0, 1, 3)
        self.body.addWidget(setup)

        quality = card()
        q = QVBoxLayout(quality)
        q.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        row = QHBoxLayout()
        row.addWidget(label("JPG quality", "heading"))
        row.addSpacing(theme.px(12))
        row.addWidget(self.quality)
        row.addSpacing(theme.px(12))
        row.addWidget(muted("Higher = bigger file, better detail"))
        row.addStretch(1)
        q.addLayout(row)
        self.quality_info = muted(self.QUALITY_INFO[95], wrap=True)
        q.addWidget(self.quality_info)
        q.addWidget(label("JPG can't store transparency, so transparent areas become white. "
                          "Animated WebP files convert only their first frame. Metadata is not kept.",
                          "caption", wrap=True))
        self.body.addWidget(quality)

        list_card = card()
        layout = QVBoxLayout(list_card)
        layout.setContentsMargins(theme.px(8), theme.px(8), theme.px(8), theme.px(8))
        self.tree = make_tree(("File", "Folder", "Size"), (300, 420, 110))
        remember("webp_tree", self.tree, header=True)
        layout.addWidget(self.tree)
        self.body.addWidget(list_card, 1)

        actions = QHBoxLayout()
        actions.setSpacing(theme.px(8))
        scan = button("Scan folder")
        scan.clicked.connect(self.scan)
        convert_all = button("Convert all listed", "primary", icons.icon("image", theme.ON_GREEN, 18))
        convert_all.clicked.connect(lambda: self.convert(False))
        convert_sel = button("Convert selected", "primary")
        convert_sel.clicked.connect(lambda: self.convert(True))
        actions.addWidget(scan)
        actions.addWidget(convert_all)
        actions.addWidget(convert_sel)
        self.summary = muted("Choose a folder to see its WebP files.")
        actions.addSpacing(theme.px(10))
        actions.addWidget(self.summary, 1)
        self.body.addLayout(actions)

    def _quality_changed(self, choice):
        self.quality_info.setText(self.QUALITY_INFO[int(choice.rstrip("%"))])

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
        setup = card()
        grid = QGridLayout(setup)
        grid.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        grid.setHorizontalSpacing(theme.px(10))
        grid.setVerticalSpacing(theme.px(10))
        grid.setColumnStretch(1, 1)
        folder_row(grid, 0, "Folder to copy", self.source, "Choose the folder to copy", on_change=self.refresh)
        self.source.editingFinished.connect(self.refresh)
        folder_row(grid, 1, "Copy into", self.dest, "Choose the destination")
        self.body.addWidget(setup)

        list_card = card()
        lv = QVBoxLayout(list_card)
        lv.setContentsMargins(theme.px(16), theme.px(14), theme.px(16), theme.px(14))
        self.checklist = FolderChecklist("Folders to copy", recursive=True, key="copy_folders")
        self.checklist.clear("Choose a folder to see its sub-folders.")
        lv.addWidget(self.checklist)
        self.body.addWidget(list_card, 1)

        run = button("Copy folder structure", "primary", icons.icon("copy_folder", theme.ON_GREEN, 18))
        run.clicked.connect(self.run)
        self.body.addWidget(run, 0, Qt.AlignLeft)

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


class Tile(QFrame):
    """A clickable theme preview."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class AppearancePage(Page):
    title = "Appearance"
    subtitle = "Choose a theme, font, size and corner style. Changes apply straight away and are remembered."

    def build(self):
        themes_card = card()
        t = QVBoxLayout(themes_card)
        t.setContentsMargins(theme.px(18), theme.px(16), theme.px(18), theme.px(16))
        t.addWidget(label("Theme", "heading"))
        t.addWidget(muted("Based on the designs you shared. Click a theme to use it."))
        grid = QGridLayout()
        grid.setSpacing(theme.px(12))
        for i, name in enumerate(PALETTES):
            grid.addWidget(self._theme_tile(name), i // 4, i % 4)
        t.addLayout(grid)
        self.body.addWidget(themes_card)

        font_card = card()
        f = QVBoxLayout(font_card)
        f.setContentsMargins(theme.px(18), theme.px(16), theme.px(18), theme.px(16))
        row = QHBoxLayout()
        row.addWidget(label("Font", "heading"))
        row.addSpacing(theme.px(12))
        installed = theme.installed_families()
        choices = [name for name in FONT_CHOICES if name in installed] or [theme.FAMILY]
        font_box = QComboBox()
        font_box.addItems(choices)
        font_box.setCurrentText(theme.FAMILY if theme.FAMILY in choices else choices[0])
        font_box.currentTextChanged.connect(lambda name: self.app.change_appearance(font=name))
        font_box.setMinimumWidth(theme.px(240))
        row.addWidget(font_box)
        row.addSpacing(theme.px(12))
        row.addWidget(muted("Only fonts installed on this PC are listed."))
        row.addStretch(1)
        f.addLayout(row)
        sample = QLabel("The quick brown fox jumps over the lazy dog. 0123456789")
        sample.setFont(theme.font("sample"))
        f.addWidget(sample)
        self.body.addWidget(font_card)

        size_card = card()
        s = QGridLayout(size_card)
        s.setContentsMargins(theme.px(18), theme.px(16), theme.px(18), theme.px(16))
        s.setHorizontalSpacing(theme.px(14))
        s.setVerticalSpacing(theme.px(12))
        self._option_row(s, 0, "Size", SIZE_CHOICES, theme.SIZE, "size",
                         "Scales the text and every button, box and table together.")
        self._option_row(s, 1, "Corner style", CORNER_STYLES, theme.RADIUS, "radius_scale",
                         "How rounded the cards, buttons and boxes are.")
        s.setColumnStretch(2, 1)
        self.body.addWidget(size_card)

        reset = button("Reset to default")
        reset.clicked.connect(self._reset)
        self.body.addWidget(reset, 0, Qt.AlignLeft)
        self.body.addStretch(1)

    def _option_row(self, grid, row, title, mapping, current, key, hint):
        grid.addWidget(label(title, "heading"), row, 0)
        box = QComboBox()
        box.addItems(list(mapping))
        box.setCurrentText(_nearest(mapping, current))
        box.setMinimumWidth(theme.px(180))
        box.currentTextChanged.connect(lambda choice, k=key, m=mapping: self.app.change_appearance(**{k: m[choice]}))
        grid.addWidget(box, row, 1)
        grid.addWidget(muted(hint), row, 2)

    def _theme_tile(self, name):
        p = PALETTES[name]
        selected = name == theme.CURRENT_THEME
        tile = Tile()
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.setStyleSheet(f"QFrame {{ background: {p['APP_BG']}; border-radius: {theme.radius(14)}px; "
                           f"border: {3 if selected else 1}px solid "
                           f"{p['GREEN'] if selected else theme.CARD_BORDER}; }}")
        v = QVBoxLayout(tile)
        v.setContentsMargins(theme.px(12), theme.px(12), theme.px(12), theme.px(12))
        strip = QHBoxLayout()
        strip.setSpacing(theme.px(8))
        for colour in (p["CARD"], p["TRACK"], p["GREEN"]):
            block = QFrame()
            block.setFixedSize(theme.px(56), theme.px(36))
            block.setStyleSheet(f"background: {colour}; border-radius: {theme.radius(8)}px; border: none;")
            strip.addWidget(block)
        strip.addStretch(1)
        v.addLayout(strip)
        name_label = QLabel(("✓ " if selected else "") + name)
        name_label.setStyleSheet(f"color: {p['TEXT']}; font-weight: bold; background: transparent; border: none;")
        v.addWidget(name_label)
        tile.clicked.connect(lambda n=name: self.app.change_appearance(theme=n))
        return tile

    def _reset(self):
        self.app.change_appearance(theme=DEFAULT_THEME, font="Inter", size=1.0, radius_scale=1.0)


NAV = [
    ("silent", "Silent videos", "silent"),
    ("gif", "GIF maker", "gif"),
    ("dupes", "Duplicate videos", "duplicate"),
    ("zip", "Zip subfolders", "zip"),
    ("webp", "WebP to JPG", "image"),
    ("copy", "Copy folder structure", "copy_folder"),
    ("appearance", "Appearance", "brush"),
]
PAGES = {
    "silent": SilentPage,
    "gif": GifTab,
    "dupes": DuplicatesPage,
    "zip": ZipPage,
    "webp": WebpPage,
    "copy": CopyPage,
    "appearance": AppearancePage,
}


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Toolbox")
        self.resize(theme.px(1280), theme.px(880))
        self.setMinimumSize(760, 520)
        self.bridge = Bridge()
        self.current_key = "silent"
        self.nav = {}
        self.pages = {}
        self._build()

    # ---------- layout ----------
    def _build(self):
        reset_remembered()
        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())

        self.stack = QStackedWidget()
        for key, cls in PAGES.items():
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(theme.px(24), theme.px(20), theme.px(24), theme.px(10))
            page = cls(self)
            hl.addWidget(page)
            self.stack.addWidget(holder)
            self.pages[key] = page

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.px(10))
        split.addWidget(self.stack)
        split.addWidget(self._activity())
        split.setStretchFactor(0, 1)
        split.setSizes([theme.px(600), theme.px(150)])
        remember("main_split", split)
        h.addWidget(split, 1)

        self.setCentralWidget(root)
        self.show_page(self.current_key)

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(theme.px(232))
        v = QVBoxLayout(side)
        v.setContentsMargins(theme.px(18), theme.px(22), theme.px(14), theme.px(18))
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.icon("logo", theme.GREEN, theme.px(34)).pixmap(theme.px(34), theme.px(34)))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Media Toolbox", "heading"))
        names.addWidget(label("Everyday file tools", "caption"))
        brand.addSpacing(theme.px(10))
        brand.addLayout(names)
        brand.addStretch(1)
        v.addLayout(brand)
        v.addSpacing(theme.px(16))
        self.nav = {}
        for key, text, icon_name in NAV:
            btn = button(text)
            btn.setFocusPolicy(Qt.NoFocus)  # the active tool shows its state, not a focus ring
            btn.setProperty("nav", "true")
            btn.setIconSize(QSize(theme.px(22), theme.px(22)))
            btn.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            v.addWidget(btn)
            self.nav[key] = (btn, icon_name)
        v.addStretch(1)
        tip = label("Resize me: drag the bars with dots between panels, and the column edges in the lists. "
                    "Sizes are remembered.", "caption", wrap=True)
        v.addWidget(tip)
        return side

    def _activity(self):
        panel = card()
        v = QVBoxLayout(panel)
        v.setContentsMargins(theme.px(16), theme.px(12), theme.px(16), theme.px(14))
        top = QHBoxLayout()
        top.setSpacing(theme.px(12))
        self.status = label("Ready", "heading")
        top.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        top.addWidget(self.bar, 1)
        clear = button("Clear log")
        clear.clicked.connect(self._clear_log)
        top.addWidget(clear)
        v.addLayout(top)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_view.setMaximumBlockCount(5000)
        v.addWidget(self.log_view, 1)
        return panel

    def show_page(self, key):
        self.current_key = key
        self.stack.setCurrentIndex(list(PAGES).index(key))
        for k, (btn, icon_name) in self.nav.items():
            active = k == key
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setIcon(icons.icon(icon_name, theme.TEXT if active else theme.MUTED, theme.px(22)))

    # ---------- appearance ----------
    def change_appearance(self, **changes):
        """Save a new appearance choice and rebuild the screen with it. Rebuilding is deferred, so it
        never happens inside the widget's own click handler."""
        current = {
            "theme": theme.CURRENT_THEME,
            "font": theme.WANTED_FAMILY,
            "size": theme.SIZE,
            "radius_scale": theme.RADIUS,
        }
        current.update(changes)
        settings.save(current)
        apply_settings(current)
        QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        log_text = self.log_view.toPlainText()
        status = self.status.text()
        progress = self.bar.value()
        theme.apply(QApplication.instance())
        self._build()
        self.log_view.setPlainText(log_text)
        self.status.setText(status)
        self.bar.setValue(progress)

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


def apply_settings(saved):
    """Apply saved appearance choices to the theme module."""
    theme.use_theme(saved.get("theme", DEFAULT_THEME))
    theme.set_family(saved.get("font", theme.BUNDLED_FAMILY))
    theme.set_look(saved.get("size", 1.0), saved.get("radius_scale", 1.0))


def main():
    app = QApplication(sys.argv)
    theme.load_fonts()
    apply_settings(settings.load())
    theme.apply(app)
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

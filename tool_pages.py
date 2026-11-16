"""The Silent videos, WebP to JPG, Zip subfolders and Copy folder structure screens."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFileDialog, QSpinBox

import collection as col
import dialogs
import fileops
import folder_tools
import icons
import jobs
import settings
import silent_videos
import theme
import webp_convert
from media_utils import VIDEO_EXTENSIONS, find_videos, open_path, show_in_explorer
from pages_common import ToolPage, plural
from widgets import (FolderChecklist, add_folder, button, divider, field_label, label, line_edit, muted,
                     results_panel, tool_row, toolbar)


def _spin(low, high, value, suffix="", width=70):
    s = QSpinBox()
    s.setRange(low, high)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setFixedWidth(width)
    return s


def file_actions(page):
    return [("Open", lambda item: page._open(item["path"])),
            ("Show in Explorer", lambda item: show_in_explorer(item["path"]))]


# ----- Silent videos -----
class SilentPage(ToolPage):
    title = "Silent videos"
    subtitle = "Find videos with no sound, check them, then move them to another folder. Moves can be undone."
    key = "silent"
    icon = "silent"
    drop_exts = VIDEO_EXTENSIONS

    def build(self):
        saved = settings.load()
        bar, rows = toolbar()
        top = tool_row()
        self.folders_row(top)
        self.scan_btn = button("Scan", "primary", icons.icon("search", theme.ON_ACCENT, 16))
        self.scan_btn.clicked.connect(self.scan)
        top.addWidget(self.scan_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.loud = QCheckBox("Also count very quiet videos")
        self.loud.setChecked(saved.get("silent_loudness", False))
        self.loud.setToolTip("Videos that have a sound track, but nothing louder than the level here, count as "
                             "silent too. Slower: every video's sound is measured.")
        self.threshold = _spin(-90, 0, int(saved.get("silent_threshold", -50)), " dB", 76)
        self.threshold.setToolTip("The loudest moment must be below this level")
        self.loud.toggled.connect(self.threshold.setEnabled)
        self.threshold.setEnabled(self.loud.isChecked())
        opts.addWidget(field_label("Sound"))
        opts.addWidget(self.loud)
        opts.addWidget(muted("Quieter than"))
        opts.addWidget(self.threshold)
        opts.addWidget(divider())
        self.dest = line_edit(saved.get("silent_dest", ""), "Choose where silent videos go")
        add_folder(opts, "Move to", self.dest, "Move silent videos to", self._save)
        self.dest.editingFinished.connect(self._save)
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)

        columns = [col.name_column(), col.folder_column(),
                   col.Column("reason", "Why", 150), col.size_column(), col.status_column()]
        self.coll = col.Collection(
            "silent", columns, "video", ("silent video", "silent videos"),
            details=lambda i: [("Why", i.get("reason", "")), ("Folder", i["root"]),
                               ("Size", fileops.human_size(i["size"])), ("Status", i.get("detail") or i.get("status")
                                                                          or "Found")],
            gallery_actions=file_actions(self),
            empty=("silent", "Add a folder, then Scan. Silent videos show up here as they're found.",
                   "Add folder…", self.pick_root))
        self.coll.tree.remove_root.connect(self.remove_root)
        self.coll.tree.file_icon = "silent"
        self.move_btn = button("Move", "primary", icons.icon("move", theme.ON_ACCENT, 16))
        self.move_btn.clicked.connect(self.move)
        self.coll.extra.addWidget(self.move_btn)
        self.coll.ticks_changed.connect(self.refresh_buttons)
        self.coll.selection_changed.connect(lambda _i: self.refresh_buttons())
        frame, v = results_panel()
        v.addWidget(self.coll)
        self.body.addWidget(frame, 1)
        self.panels.append(self.coll.tree_panel)
        self.coll.set_roots(self.roots)
        self.refresh_buttons()

    def _save(self):
        settings.save({"silent_dest": self.dest.text().strip(), "silent_loudness": self.loud.isChecked(),
                       "silent_threshold": self.threshold.value()})

    def _open(self, path):
        try:
            open_path(path)
        except OSError as exc:
            dialogs.error("Couldn't open the file", str(exc))

    def roots_changed(self):
        self.coll.set_roots(self.roots)
        self.refresh_buttons()

    def refresh_buttons(self):
        n = len(self.roots)
        self.set_main(self.scan_btn, f"Scan {plural(n, 'folder')}" if n else "Scan", f"a scan of {plural(n, 'folder')}")
        t = len(self.coll.targets())
        self.move_btn.setText(f"Move {plural(t, 'video')}" if t else "Move")
        self.move_btn.setVisible(bool(self.coll.items()))

    # ----- scanning -----
    def scan(self):
        if not self.check_roots():
            return
        self._save()
        roots = self.live_roots()
        self.coll.set_items([])
        self.app.start(jobs.Job("Finding silent videos", self._scan_job, roots, self.recursive.isChecked(),
                                self.loud.isChecked(), self.threshold.value(), short="Scanning",
                                done=lambda job: self.refresh_buttons()))

    def _scan_job(self, roots, recursive, loud, threshold, log, progress):
        def found(path, root, reason):
            item = col.make_item(path, root, reason=reason)
            self.app.on_main(lambda: self.coll.add_items([item]))

        silent = silent_videos.scan(roots, recursive, loud, threshold, log, progress, found)
        return {"summary": f"{plural(len(silent), 'silent video')} found",
                "next": ("Move them…", self.move) if silent else None}

    # ----- moving -----
    def move(self):
        targets = self.coll.targets()
        if not targets:
            dialogs.info("Tick the videos to move", "Tick videos with their tick box or Ctrl+click, or select one. "
                         "Ctrl+A ticks everything shown.", icon_name="info")
            return
        dest = self.dest.text().strip()
        if not dest:
            dest = QFileDialog.getExistingDirectory(self, "Move silent videos to")
            if not dest:
                return
            self.dest.setText(dest)
            self._save()
        ops = [{"src": i["path"], "dst_dir": dest, "copy": False} for i in targets]
        chosen = dialogs.review_moves(f"Move {plural(len(ops), 'silent video')}?", ops)
        if not chosen:
            return
        for op in chosen:
            self.coll.update(op["src"], status="Queued")
        by_dest = {}
        for op in chosen:
            by_dest.setdefault(op["dst_dir"], []).append(op["src"])
        self.app.start(jobs.Job("Moving silent videos", self._move_job, by_dest, short="Moving",
                                done=self._moved))

    def _move_job(self, by_dest, log, progress):
        moved_all, failed_all = [], 0
        for dest, files in by_dest.items():
            def done_one(src, ok):
                self.app.on_main(lambda: self.coll.update(src, status="Done" if ok else "Failed"))
            moved, failed = silent_videos.move_videos(files, dest, log, progress, done_one)
            moved_all += moved
            failed_all += failed
        return {"summary": f"{plural(len(moved_all), 'video')} moved" + (f", {failed_all} failed" if failed_all
                                                                           else ""),
                "next": ("Show the log of moves", lambda: (self.app.toggle_drawer(True),
                                                           self.app.drawer.show_moves())),
                "moved": moved_all}

    def _moved(self, job):
        result = job.result if isinstance(job.result, dict) else {}
        moved = [s for s, _d in result.get("moved", [])]
        if moved:
            self.coll.remove(moved)
            self.app.toast(f"Moved {plural(len(moved), 'video')}. Ctrl+Z puts them back.", "ok")
        self.refresh_buttons()

    # ----- keys -----
    def tick_all(self):
        self.coll.tick_all()

    def step(self, delta):
        return self.coll.step(delta)

    def zoom(self, step):
        return self.coll.zoom(step)

    def fit(self, actual):
        return self.coll.fit(actual)

    def space(self):
        return self.coll.space()

    def leave_full_view(self):
        return self.coll.leave_full_view()


# ----- WebP to JPG -----
class WebpPage(ToolPage):
    title = "WebP to JPG"
    subtitle = "Turn .webp pictures into .jpg beside each original. Originals can go to the Recycle Bin."
    key = "webp"
    icon = "image"
    drop_exts = {".webp"}

    def build(self):
        saved = settings.load()
        bar, rows = toolbar()
        top = tool_row()
        self.folders_row(top)
        self.go_btn = button("Convert", "primary", icons.icon("image", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.convert)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        opts.addWidget(field_label("JPG quality"))
        self.quality = _spin(1, 100, int(saved.get("webp_quality", 92)), "%")
        self.quality.setToolTip("Higher keeps more detail and makes bigger files. 90 to 95 suits most pictures.")
        opts.addWidget(self.quality)
        opts.addWidget(divider())
        self.recycle = QCheckBox("Send each original to the Recycle Bin once its JPG is made")
        self.recycle.setChecked(saved.get("webp_recycle", False))
        opts.addWidget(self.recycle)
        opts.addStretch(1)
        opts.addWidget(label("Transparent parts become white. Metadata isn't kept.", "caption"))
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)

        columns = [col.name_column(), col.folder_column(), col.size_column(), col.status_column()]
        self.coll = col.Collection(
            "webp", columns, "image", ("picture", "pictures"), default_view="grid",
            details=lambda i: [("Folder", i["root"] + ("/" + i["rel_folder"] if i["rel_folder"] else "")),
                               ("Size", fileops.human_size(i["size"])),
                               ("Status", i.get("detail") or i.get("status") or "Not converted yet")],
            gallery_actions=file_actions(self),
            empty=("image", "Add a folder to see its .webp pictures here.", "Add folder…", self.pick_root))
        self.coll.tree.remove_root.connect(self.remove_root)
        self.coll.ticks_changed.connect(self.refresh_buttons)
        frame, v = results_panel()
        v.addWidget(self.coll)
        self.body.addWidget(frame, 1)
        self.panels.append(self.coll.tree_panel)
        self.coll.set_roots(self.roots)
        self.refresh_buttons()
        self._loaded = False

    _open = SilentPage._open

    def shown(self):
        if not self._loaded and self.roots:
            self._loaded = True
            self.load()

    def roots_changed(self):
        self.coll.set_roots(self.roots)
        self.load()

    def load(self):
        roots = self.live_roots()
        recursive = self.recursive.isChecked()
        self.app.start(jobs.Job("Listing pictures", self._list_job, roots, recursive, short="Listing",
                                done=self._listed))

    def _list_job(self, roots, recursive, log, progress):
        found = []
        for n, root in enumerate(roots):
            progress(n, len(roots), f"Looking in {Path(root).name}")
            found += [col.make_item(p, root) for p in webp_convert.find_webp(root, recursive)]
        return {"summary": f"{plural(len(found), '.webp picture')} found", "items": found}

    def _listed(self, job):
        if isinstance(job.result, dict):
            self.coll.set_items(job.result["items"])
            self.coll.set_empty("No .webp pictures in these folders." if self.roots else
                                "Add a folder to see its .webp pictures here.", "Add folder…")
        self.refresh_buttons()

    def refresh_buttons(self):
        ticked = len(self.coll.ticked())
        total = len(self.coll.items())
        if ticked:
            self.set_main(self.go_btn, f"Convert {plural(ticked, 'ticked picture')}", plural(ticked, "picture"))
        else:
            self.set_main(self.go_btn, f"Convert all {plural(total, 'picture')}" if total else "Convert",
                          plural(total, "picture"))

    def convert(self):
        items = self.coll.ticked() or self.coll.items()
        items = [i for i in items if Path(i["path"]).exists()]
        if not items:
            dialogs.info("Nothing to convert", "Add a folder with .webp pictures first.", icon_name="image")
            return
        quality, recycle = self.quality.value(), self.recycle.isChecked()
        settings.save({"webp_quality": quality, "webp_recycle": recycle})
        if recycle and not dialogs.ask(
                f"Convert {plural(len(items), 'picture')} and send the originals to the Recycle Bin?",
                "Each original goes to the Recycle Bin only after its JPG is made. You can restore them from there.",
                f"Convert and send {plural(len(items), 'original')} to the Recycle Bin",
                items=[i["name"] for i in items]):
            return
        for i in items:
            self.coll.update(i["path"], status="Queued", detail="")
        self.app.start(jobs.Job("Converting pictures", self._convert_job, [i["path"] for i in items], quality,
                                recycle, short="Converting", done=lambda _j: self.refresh_buttons()))

    def _convert_job(self, files, quality, recycle, log, progress):
        def state(path, status, detail):
            self.app.on_main(lambda: self.coll.update(path, status=status, detail=detail))
        try:
            made, failed = webp_convert.convert_files(files, quality, recycle, log, progress, state)
        finally:
            self.app.on_main(lambda: [self.coll.update(p, status="") for p in files
                                      if (self.coll.find(p) or {}).get("status") in ("Queued", "Working")])
        folder = str(Path(files[0]).parent)
        return {"summary": f"{made} made, {failed} failed",
                "next": ("Show in Explorer", lambda: show_in_explorer(files[0] if not recycle else folder))}

    tick_all = SilentPage.tick_all
    step = SilentPage.step
    zoom = SilentPage.zoom
    fit = SilentPage.fit
    space = SilentPage.space
    leave_full_view = SilentPage.leave_full_view


# ----- Zip subfolders -----
class ZipPage(ToolPage):
    title = "Zip subfolders"
    subtitle = "Make one .zip for each folder inside a folder. Untick the ones to leave out."
    key = "zip"
    icon = "zip"

    def build(self):
        saved = settings.load()
        bar, rows = toolbar()
        top = tool_row()
        self.src = line_edit(saved.get("zip_src", ""), "Choose the folder whose folders you want zipped")
        add_folder(top, "Folder", self.src, "Choose the folder", self._load)
        self.src.editingFinished.connect(self._load)
        top.addWidget(divider())
        self.go_btn = button("Zip", "primary", icons.icon("zip", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.run)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.dst = line_edit(saved.get("zip_dst", ""), "Empty = inside the folder above")
        add_folder(opts, "Save zips to", self.dst, "Save zips to")
        opts.addWidget(label("A zip whose name is taken gets “(2)”.", "caption"))
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)
        self.list = FolderChecklist("Folders to zip", False, "zip", "Choose a folder to list the folders inside it.",
                                    self._browse, "Choose a folder…")
        self.list.changed.connect(self.refresh_buttons)
        frame, v = results_panel()
        v.addWidget(self.list)
        self.body.addWidget(frame, 1)
        self._load()

    def drop_text(self, paths):
        dirs = [p for p in paths if Path(p).is_dir()]
        return f"Drop to use {Path(dirs[0]).name}" if len(dirs) == 1 else ""

    def dropped(self, paths):
        self.src.setText(str(Path(next(p for p in paths if Path(p).is_dir()))))
        self._load()

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose the folder", self.src.text())
        if chosen:
            self.src.setText(chosen)
            self._load()

    def _load(self):
        folder = self.src.text().strip()
        settings.save({"zip_src": folder})
        if folder and Path(folder).is_dir():
            self.list.load(folder)
        else:
            self.list.clear("" if not folder else "That folder can't be found.")
        self.refresh_buttons()

    def refresh_buttons(self):
        n = self.list.ticked_count()
        self.set_main(self.go_btn, f"Zip {plural(n, 'folder')}" if n else "Zip", f"zipping {plural(n, 'folder')}")

    def tick_all(self):
        self.list.tick_all()

    def run(self):
        src = self.src.text().strip()
        if not Path(src).is_dir():
            dialogs.info("Choose a folder first", "Pick the folder whose folders you want zipped.", icon_name="folder")
            return
        only = self.list.checked_names()
        if not only:
            dialogs.info("Nothing ticked", "Tick at least one folder to zip.", icon_name="info")
            return
        dst = self.dst.text().strip() or None
        settings.save({"zip_dst": dst or ""})
        self.app.start(jobs.Job(f"Zipping {plural(len(only), 'folder')}", self._job, src, dst, only, short="Zipping"))

    def _job(self, src, dst, only, log, progress):
        made, failed = folder_tools.zip_subfolders(src, dst, log, progress, only)
        target = dst or src
        return {"summary": f"{made} made, {failed} failed", "next": ("Open the folder", lambda: open_path(target))}


# ----- Copy folder structure -----
class CopyPage(ToolPage):
    title = "Copy folder structure"
    subtitle = "Recreate a folder's folders somewhere else, without any files. Untick folders to leave them out."
    key = "copy"
    icon = "copy_folder"

    def build(self):
        saved = settings.load()
        bar, rows = toolbar()
        top = tool_row()
        self.src = line_edit(saved.get("copy_src", ""), "Choose the folder to copy")
        add_folder(top, "Copy", self.src, "Choose the folder to copy", self._load)
        self.src.editingFinished.connect(self._load)
        top.addWidget(divider())
        self.go_btn = button("Copy", "primary", icons.icon("copy_folder", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.run)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.dst = line_edit(saved.get("copy_dst", ""), "Choose where the copy is made")
        add_folder(opts, "Into", self.dst, "Make the copy in")
        opts.addWidget(label("No files are copied. A taken name gets “(2)”.", "caption"))
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)
        self.list = FolderChecklist("Folders to copy", True, "copy", "Choose a folder to see the folders inside it.",
                                    self._browse, "Choose a folder…")
        self.list.changed.connect(self.refresh_buttons)
        frame, v = results_panel()
        v.addWidget(self.list)
        self.body.addWidget(frame, 1)
        self._load()

    def drop_text(self, paths):
        dirs = [p for p in paths if Path(p).is_dir()]
        return f"Drop to use {Path(dirs[0]).name}" if len(dirs) == 1 else ""

    def dropped(self, paths):
        self.src.setText(str(Path(next(p for p in paths if Path(p).is_dir()))))
        self._load()

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose the folder to copy", self.src.text())
        if chosen:
            self.src.setText(chosen)
            self._load()

    def _load(self):
        folder = self.src.text().strip()
        settings.save({"copy_src": folder})
        if folder and Path(folder).is_dir():
            self.list.load(folder)
        else:
            self.list.clear("" if not folder else "That folder can't be found.")
        self.refresh_buttons()

    def refresh_buttons(self):
        n = self.list.ticked_count() + (1 if Path(self.src.text().strip() or "\0").is_dir() else 0)
        self.set_main(self.go_btn, f"Copy {plural(n, 'folder')}" if n else "Copy", f"copying {plural(n, 'folder')}")

    def tick_all(self):
        self.list.tick_all()

    def run(self):
        src, dst = self.src.text().strip(), self.dst.text().strip()
        if not Path(src).is_dir():
            dialogs.info("Choose a folder first", "Pick the folder whose folders you want to copy.", icon_name="folder")
            return
        if not dst:
            dst = QFileDialog.getExistingDirectory(self, "Make the copy in")
            if not dst:
                return
            self.dst.setText(dst)
        settings.save({"copy_dst": dst})
        skip = self.list.unchecked_paths()
        self.app.start(jobs.Job("Copying folder structure", self._job, src, dst, skip, short="Copying"))

    def _job(self, src, dst, skip, log, progress):
        count, target = folder_tools.copy_folder_structure(src, dst, log, progress, skip)
        return {"summary": f"{plural(count, 'folder')} made", "next": ("Open the copy", lambda: open_path(target))}

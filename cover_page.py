"""The Video thumbnails screen: choose the picture File Explorer shows for a video.

Pick a frame from the video, or any picture, for each video (or for every ticked video at once), then set
them all with one button. The video and sound aren't re-encoded; the original goes to the Recycle Bin."""
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QHBoxLayout, QSlider, QSplitter, QVBoxLayout

import collection as col
import dialogs
import fileops
import icons
import jobs
import settings
import theme
import video_covers as vc
from gif_page import Frame, fmt_time, to_pixmap
from media_utils import VIDEO_EXTENSIONS, find_videos, open_path, probe_video
from pages_common import ToolPage, plural
from tool_pages import SilentPage, file_actions
from widgets import (ElidedLabel, Segmented, button, divider, label, line_edit, muted, remember, results_panel,
                     tool_row, toolbar)


def pending_text(item):
    p = item.get("pending")
    if not p:
        return ""
    how, value = p
    if how == "frame":
        return f"Frame at {fmt_time(value)}"
    if how == "percent":
        return f"Frame at {value:g}%"
    if how == "file":
        return f"Picture: {Path(value).name}"
    return "Remove its own"


class CoverPage(ToolPage):
    title = "Video thumbnails"
    subtitle = ("Choose the picture File Explorer shows for a video: a frame from it, or any picture. The video "
                "isn't re-encoded; the original goes to the Recycle Bin.")
    key = "cover"
    icon = "cover"
    drop_exts = VIDEO_EXTENSIONS

    def build(self):
        saved = settings.load()
        self.current = None
        self._token = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._preview_frame)

        bar, rows = toolbar()
        top = tool_row()
        self.folders_row(top)
        self.go_btn = button("Set thumbnails", "primary", icons.icon("cover", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.apply_all)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.keep_date = QCheckBox("Keep each video's modified date")
        self.keep_date.setChecked(saved.get("cover_keep_date", False))
        self.keep_date.setToolTip("File Explorer may keep showing the old thumbnail for a video whose date "
                                  "doesn't change, until its thumbnail cache is cleared.")
        self.keep_date.toggled.connect(lambda on: settings.save({"cover_keep_date": on}))
        opts.addWidget(self.keep_date)
        opts.addStretch(1)
        opts.addWidget(label("Works for MP4, M4V and MKV. File Explorer shows MKV thumbnails only with an add-on "
                             "such as Icaros.", "caption"))
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)

        # every ticked video at once
        self.selbar = QFrame()
        self.selbar.setObjectName("selbar")
        sb = QHBoxLayout(self.selbar)
        sb.setContentsMargins(theme.PAD, 4, 6, 4)
        sb.setSpacing(theme.GAP)
        self.sel_count = label("", "heading")
        sb.addWidget(self.sel_count)
        sb.addWidget(divider())
        sb.addWidget(muted("Frame at"))
        self.sel_percent = line_edit("10", width=52)
        self.sel_percent.setAlignment(Qt.AlignRight)
        self.sel_percent.setToolTip("How far into each video, as a percentage of its length")
        sb.addWidget(self.sel_percent)
        sb.addWidget(muted("% of each video"))
        use_pct = button("Use for ticked")
        use_pct.clicked.connect(self._ticked_percent)
        sb.addWidget(use_pct)
        use_pic = button("Use a picture for ticked…")
        use_pic.clicked.connect(self._ticked_picture)
        sb.addWidget(use_pic)
        rm = button("Remove their own", "danger-ghost", tip="Go back to the frame Windows picks")
        rm.clicked.connect(lambda: self._mark(self.coll.ticked(), ("remove", None)))
        sb.addWidget(rm)
        clear = button("Clear choices", "ghost")
        clear.clicked.connect(lambda: self._mark(self.coll.ticked(), None))
        sb.addWidget(clear)
        sb.addStretch(1)
        self.selbar.hide()
        self.body.addWidget(self.selbar)

        columns = [col.name_column(), col.folder_column(),
                   col.Column("own", "Now", 96, text=lambda i: {True: "Own picture", False: "A frame"}.get(
                       i.get("has_cover"), "…")),
                   col.Column("pending", "New thumbnail", 150, text=pending_text,
                              sort=lambda i: pending_text(i)),
                   col.size_column(), col.status_column()]
        self.coll = col.Collection(
            "cover", columns, "video", ("video", "videos"), default_view="grid",
            details=lambda i: [("Folder", i["root"] + ("/" + i["rel_folder"] if i["rel_folder"] else "")),
                               ("Now", {True: "its own picture", False: "a frame Windows picks"}.get(
                                   i.get("has_cover"), "checking…")),
                               ("New", pending_text(i) or "nothing chosen"),
                               ("Size", fileops.human_size(i["size"]))],
            subline=lambda i: pending_text(i) or ("Own picture" if i.get("has_cover") else
                                                  "" if vc.supported(i["path"]) else "Can't change this kind"),
            gallery_actions=file_actions(self),
            empty=("image", "Add a folder to see its videos and their thumbnails here.", "Add folder…",
                   self.pick_root))
        self.coll.tree.remove_root.connect(self.remove_root)
        self.coll.tree.file_icon = "silent"
        self.coll.ticks_changed.connect(self._ticks_changed)
        self.coll.selection_changed.connect(self._on_current)
        self.coll.view_changed.connect(lambda v: self.editor.setVisible(v != "gallery"))
        list_frame, lv = results_panel()
        lv.addWidget(self.coll)

        # the editor for the selected video
        self.editor, ev = results_panel()
        self.editor.setMinimumWidth(340)
        head = QHBoxLayout()
        head.addWidget(label("Thumbnail", "heading"))
        self.editor_name = ElidedLabel("Click a video to choose its thumbnail.")
        head.addWidget(self.editor_name, 1)
        ev.addLayout(head)
        self.source = Segmented([("frame", "A frame from the video"), ("file", "A picture")], "frame")
        self.source.changed.connect(self._source_changed)
        ev.addWidget(self.source, 0, Qt.AlignLeft)
        # from the video
        self.frame_row = QFrame()
        fr = QVBoxLayout(self.frame_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(6)
        where = QHBoxLayout()
        where.addWidget(muted("Where in the video"))
        where.addStretch(1)
        self.time = label("", "value")
        where.addWidget(self.time)
        fr.addLayout(where)
        self.pos = QSlider(Qt.Horizontal)
        self.pos.setRange(0, 1000)
        self.pos.valueChanged.connect(lambda _v: (self._time_label(), self._preview_timer.start()))
        fr.addWidget(self.pos)
        steps = tool_row()
        for text, delta, tip in (("− 1 s", -1.0, "Back one second"), ("− frame", "-f", "Back one frame"),
                                 ("+ frame", "+f", "Forward one frame"), ("+ 1 s", 1.0, "Forward one second")):
            b = button(text, "ghost", tip=tip)
            b.clicked.connect(lambda _c=False, d=delta: self._nudge(d))
            steps.addWidget(b)
        steps.addStretch(1)
        fr.addLayout(steps)
        ev.addWidget(self.frame_row)
        # from a picture
        self.file_row = QFrame()
        fh = QHBoxLayout(self.file_row)
        fh.setContentsMargins(0, 0, 0, 0)
        pick = button("Choose picture…", icon=icons.icon("folder", theme.TEXT, 16))
        pick.clicked.connect(self._pick_picture)
        fh.addWidget(pick)
        self.picture_label = ElidedLabel("No picture chosen", "muted", Qt.ElideMiddle)
        fh.addWidget(self.picture_label, 1)
        self.file_row.hide()
        ev.addWidget(self.file_row)
        acts = tool_row()
        self.use_btn = button("Use this", "primary", tip="Choose this for the video. Set thumbnails applies it.")
        self.use_btn.clicked.connect(self._use_current)
        acts.addWidget(self.use_btn)
        self.remove_btn = button("Remove its own", "danger-ghost", tip="Go back to the frame Windows picks")
        self.remove_btn.clicked.connect(lambda: self.current and self._mark([self.current], ("remove", None)))
        acts.addWidget(self.remove_btn)
        self.clear_btn = button("Clear choice", "ghost")
        self.clear_btn.clicked.connect(lambda: self.current and self._mark([self.current], None))
        acts.addWidget(self.clear_btn)
        acts.addStretch(1)
        ev.addLayout(acts)
        pics = QHBoxLayout()
        pics.setSpacing(theme.GAP)
        self.now_view, self.new_view = Frame(), Frame()
        pics.addWidget(self._box("Now", self.now_view), 1)
        pics.addWidget(self._box("New", self.new_view), 1)
        ev.addLayout(pics, 1)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.GAP)
        split.addWidget(list_frame)
        split.addWidget(self.editor)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        remember("cover_split", split)
        self.body.addWidget(split, 1)
        self.panels.append(self.coll.tree_panel)
        self.coll.set_roots(self.roots)
        self._clear_editor()
        self._loaded = False
        self.editor.setVisible(self.coll.view() != "gallery")
        self.refresh_buttons()

    _open = SilentPage._open

    def _box(self, caption, view):
        box = QFrame()
        box.setObjectName("preview")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)
        lay.addWidget(label(caption, "caption"))
        lay.addWidget(view, 1)
        return box

    # ----- loading -----
    def shown(self):
        if not self._loaded and self.roots:
            self._loaded = True
            self.load()

    def roots_changed(self):
        self.coll.set_roots(self.roots)
        self.load()

    def load(self):
        roots, recursive = self.live_roots(), self.recursive.isChecked()
        self.app.start(jobs.Job("Listing videos", self._list_job, roots, recursive, short="Listing",
                                done=self._listed))

    def _list_job(self, roots, recursive, log, progress):
        items = []
        for n, root in enumerate(roots):
            progress(n, len(roots), f"Looking in {Path(root).name}")
            items += [col.make_item(p, root, has_cover=None, pending=None, info={}) for p in find_videos(root, recursive)]
        return {"summary": f"{plural(len(items), 'video')} found", "items": items}

    def _listed(self, job):
        if not isinstance(job.result, dict):
            return
        items = job.result["items"]
        self.coll.set_items(items)
        self.coll.set_empty("No videos in these folders." if self.roots else
                            "Add a folder to see its videos and their thumbnails here.", "Add folder…")
        self.refresh_buttons()
        threading.Thread(target=self._read_info, args=([i["path"] for i in items],), daemon=True).start()

    def _read_info(self, todo):
        for path in todo:
            try:
                info = probe_video(path)
                own = vc.has_cover(path) if vc.supported(path) else False
            except Exception:
                info, own = {}, False
            self.app.on_main(lambda p=path, i=info, o=own: self._set_info(p, i, o))

    def _set_info(self, path, info, own):
        item = self.coll.update(path, info=info, has_cover=own)
        if item is not None and item is self.current:
            self._show_editor(item)

    # ----- the editor -----
    def _on_current(self, item):
        if item is None or item is self.current:
            return
        self.current = item
        self._show_editor(item)

    def _clear_editor(self):
        self.current = None
        self.editor_name.setText("Click a video to choose its thumbnail.")
        self.now_view.show_message("No video selected")
        self.new_view.show_message("")
        self.use_btn.setEnabled(False)
        self.remove_btn.hide()
        self.clear_btn.hide()

    def _show_editor(self, item):
        self.editor_name.setText(item["name"])
        ok = vc.supported(item["path"])
        for w in (self.use_btn, self.source, self.frame_row, self.file_row):
            w.setEnabled(ok)
        self.remove_btn.setVisible(ok and bool(item.get("has_cover")))
        self.clear_btn.setVisible(bool(item.get("pending")))
        pending = item.get("pending")
        self.pos.blockSignals(True)
        if pending and pending[0] == "frame" and (item.get("info") or {}).get("duration"):
            self.pos.setValue(int(pending[1] / item["info"]["duration"] * 1000))
        elif not pending or pending[0] != "frame":
            self.pos.setValue(100)
        self.pos.blockSignals(False)
        self._time_label()
        if pending and pending[0] == "file":
            self.source.set_value("file")
            self._source_changed("file", keep=True)
            self.picture_label.setText(pending[1])
        else:
            self.source.set_value("frame")
            self._source_changed("frame", keep=True)
        self._show_now(item)
        if not ok:
            self.new_view.show_message(vc.why_not(item["path"]))
        elif self.source.value() == "frame":
            self._preview_frame()
        else:
            self._preview_picture()

    def _show_now(self, item):
        image = self.coll.thumbs.get(item["path"])
        if image is not None:
            from PySide6.QtGui import QPixmap
            self.now_view.show_frame(QPixmap.fromImage(image))
        else:
            self.now_view.show_message("Making a preview…")
            QTimer.singleShot(600, lambda: self.current is item and self._show_now(item))

    def _duration(self):
        return ((self.current or {}).get("info") or {}).get("duration") or 0

    def _seconds(self):
        return self._duration() * self.pos.value() / 1000

    def _time_label(self):
        d = self._duration()
        self.time.setText(f"{fmt_time(self._seconds())} of {fmt_time(d)}" if d else "")

    def _nudge(self, delta):
        d = self._duration()
        if not d:
            return
        if isinstance(delta, str):
            fps = ((self.current or {}).get("info") or {}).get("fps") or 25
            delta = (1 if delta == "+f" else -1) / fps
        self.pos.setValue(int(max(0, min(d, self._seconds() + delta)) / d * 1000))

    def _source_changed(self, value, keep=False):
        self.frame_row.setVisible(value == "frame")
        self.file_row.setVisible(value == "file")
        if not keep and self.current:
            self._preview_frame() if value == "frame" else self._preview_picture()

    def _preview_frame(self):
        item = self.current
        if not item or not vc.supported(item["path"]) or self.source.value() != "frame":
            return
        self._token += 1
        token, path, seconds = self._token, item["path"], self._seconds()

        def work():
            img = vc.frame_at(path, seconds, 640)
            self.app.on_main(lambda: token == self._token and (
                self.new_view.show_frame(to_pixmap(img)) if img is not None
                else self.new_view.show_message("This frame can't be read")))
        threading.Thread(target=work, daemon=True).start()

    def _pick_picture(self):
        start = str(Path(self.current["path"]).parent) if self.current else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture", start,
                                              "Pictures (*.jpg *.jpeg *.png *.webp *.bmp *.gif)")
        if path:
            self.picture_label.setText(path)
            self._preview_picture()

    def _preview_picture(self):
        path = self.picture_label.text_full()
        if not path or not Path(path).exists():
            self.new_view.show_message("Choose a picture")
            return
        try:
            self.new_view.show_frame(to_pixmap(vc.picture_from_file(path, 640)))
        except Exception as exc:
            self.new_view.show_message(f"That picture can't be read: {exc}")

    def _use_current(self):
        if not self.current:
            return
        if self.source.value() == "frame":
            choice = ("frame", round(self._seconds(), 3))
        else:
            path = self.picture_label.text_full()
            if not path or not Path(path).exists():
                dialogs.info("Choose a picture first", "Use Choose picture… to pick the picture.",
                             icon_name="image")
                return
            choice = ("file", path)
        self._mark([self.current], choice)

    def _mark(self, items, choice):
        items = [i for i in items if choice is None or vc.supported(i["path"])]
        for item in items:
            self.coll.update(item["path"], pending=choice, status="", detail="")
        if self.current in items:
            self.clear_btn.setVisible(choice is not None)
        self.refresh_buttons()

    # ----- ticked videos -----
    def _ticks_changed(self):
        ticked = self.coll.ticked()
        self.selbar.setVisible(len(ticked) >= 2)
        self.sel_count.setText(f"{len(ticked)} ticked")
        self.refresh_buttons()

    def _ticked_percent(self):
        try:
            pct = float(self.sel_percent.text())
        except ValueError:
            pct = -1
        if not 0 <= pct <= 100:
            self.app.toast("Type a percentage from 0 to 100.", "warn")
            return
        skipped = [i for i in self.coll.ticked() if not vc.supported(i["path"])]
        self._mark(self.coll.ticked(), ("percent", pct))
        if skipped:
            self.app.toast(f"{plural(len(skipped), 'video')} skipped: only MP4, M4V and MKV can have a thumbnail of "
                           "their own.", "info")

    def _ticked_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture for the ticked videos", "",
                                              "Pictures (*.jpg *.jpeg *.png *.webp *.bmp *.gif)")
        if path:
            self._mark(self.coll.ticked(), ("file", path))

    # ----- applying -----
    def refresh_buttons(self):
        n = sum(1 for i in self.coll.items() if i.get("pending"))
        self.set_main(self.go_btn, f"Set {plural(n, 'thumbnail')}" if n else "Set thumbnails",
                      plural(n, "thumbnail"))

    def apply_all(self):
        todo = [i for i in self.coll.items() if i.get("pending") and Path(i["path"]).exists()]
        if not todo:
            dialogs.info("Choose some thumbnails first", "Click a video, pick a frame or a picture and click Use "
                         "this. Tick several videos to choose for all of them at once.", icon_name="image")
            return
        if not dialogs.ask(f"Set {plural(len(todo), 'thumbnail')}?",
                           "Each video is rewritten with its new thumbnail (the video and sound are copied, not "
                           "re-encoded). Each original goes to the Recycle Bin, so it can be restored. That needs "
                           "as much free space as the videos take.", f"Set {plural(len(todo), 'thumbnail')}",
                           items=[(i["name"], pending_text(i)) for i in todo], icon_name="image"):
            return
        for i in todo:
            self.coll.update(i["path"], status="Queued", detail="")
        work = [(i["path"], i["pending"]) for i in todo]
        self.app.start(jobs.Job(f"Setting {plural(len(work), 'thumbnail')}", self._apply_job, work,
                                self.keep_date.isChecked(), short="Thumbnails", own_log=True,
                                done=self._applied))

    def _apply_job(self, work, keep_date, log, progress):
        def state(path, status, detail):
            self.app.on_main(lambda: self.coll.update(path, status=status, detail=detail))
        try:
            done, failed = vc.apply(work, log, progress, state, keep_date)
        finally:
            paths_ = [w[0] for w in work]
            self.app.on_main(lambda: [self.coll.update(p, status="") for p in paths_
                                      if (self.coll.find(p) or {}).get("status") in ("Queued", "Working")])
        return {"summary": f"{done} set, {failed} failed",
                "next": ("Open the folder", lambda: open_path(str(Path(work[0][0]).parent)))}

    def _applied(self, job):
        for item in self.coll.items():
            if item.get("status") == "Done":
                removed = (item.get("pending") or ("",))[0] == "remove"
                try:
                    size = Path(item["path"]).stat().st_size
                except OSError:
                    size = item["size"]
                self.coll.update(item["path"], pending=None, has_cover=not removed, size=size)
        self.coll.thumbs.forget()
        self.coll.grid.viewport().update()
        if self.current:
            self._show_editor(self.current)
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

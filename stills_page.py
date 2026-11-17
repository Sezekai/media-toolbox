"""The Make stills screen: two pictures from each video (one a second in, one from the middle) to search in
Google Lens. They're named so Lens Library's Import matches them back to their videos."""
from pathlib import Path

from PySide6.QtCore import Qt

import collection as col
import dialogs
import fileops
import icons
import jobs
import settings
import stills
import theme
from media_utils import VIDEO_EXTENSIONS, find_videos, open_path, show_in_explorer
from pages_common import ToolPage, plural
from tool_pages import SilentPage, file_actions
from widgets import add_folder, button, label, line_edit, results_panel, tool_row, toolbar


class StillsPage(ToolPage):
    title = "Make stills"
    subtitle = ("Two pictures from each video, one a second in and one from the middle, named "
                "“video - start.jpg” and “video - middle.jpg” for Google Lens and Lens Library.")
    key = "stills"
    icon = "stills"
    drop_exts = VIDEO_EXTENSIONS

    def build(self):
        saved = settings.load()
        bar, rows = toolbar()
        top = tool_row()
        self.folders_row(top, recursive_default=False)
        self.go_btn = button("Make stills", "primary", icons.icon("stills", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.make)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.out = line_edit(saved.get("stills_out", ""), "Empty = beside each video")
        add_folder(opts, "Put stills in", self.out, "Put the stills in", self._out_changed)
        self.out.editingFinished.connect(self._out_changed)
        opts.addWidget(label("Videos that already have both stills there are skipped.", "caption"))
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)

        columns = [col.name_column(), col.folder_column(),
                   col.Column("has", "Stills", 110, text=self._has_text, sort=lambda i: self._has_count(i)),
                   col.size_column(), col.status_column()]
        self.coll = col.Collection(
            "stills", columns, "video", ("video", "videos"), default_view="list",
            details=lambda i: [("Folder", i["root"] + ("/" + i["rel_folder"] if i["rel_folder"] else "")),
                               ("Stills", self._has_text(i)), ("Size", fileops.human_size(i["size"])),
                               ("Result", i.get("detail") or "")],
            subline=self._has_text, gallery_actions=file_actions(self),
            empty=("stills", "Add a folder of videos, or drag videos in. Each gets a start and a middle still.",
                   "Add folder…", self.pick_root))
        self.coll.tree.remove_root.connect(self.remove_root)
        self.coll.tree.file_icon = "silent"
        self.coll.ticks_changed.connect(self.refresh_buttons)
        frame, v = results_panel()
        v.addWidget(self.coll)
        self.body.addWidget(frame, 1)
        self.panels.append(self.coll.tree_panel)
        self.coll.set_roots(self.roots)
        self._loaded = False
        self.refresh_buttons()

    _open = SilentPage._open

    def _out_dir(self):
        return self.out.text().strip() or None

    def _out_changed(self):
        settings.save({"stills_out": self.out.text().strip()})
        for item in self.coll.items():
            self.coll.model.changed(item)

    def _has_count(self, item):
        return sum(1 for p in stills.targets(item["path"], self._out_dir()).values() if p.exists())

    def _has_text(self, item):
        return {0: "", 1: "1 of 2", 2: "Both made"}[self._has_count(item)]

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
            items += [col.make_item(p, root) for p in find_videos(root, recursive)]
        return {"summary": f"{plural(len(items), 'video')} found", "items": items}

    def _listed(self, job):
        if isinstance(job.result, dict):
            self.coll.set_items(job.result["items"])
            self.coll.set_empty("No videos in these folders." if self.roots else
                                "Add a folder of videos, or drag videos in. Each gets a start and a middle still.",
                                "Add folder…")
        self.refresh_buttons()

    # ----- making -----
    def refresh_buttons(self):
        ticked, total = len(self.coll.ticked()), len(self.coll.items())
        if ticked:
            self.set_main(self.go_btn, f"Make stills of {plural(ticked, 'ticked video')}", plural(ticked, "video"))
        else:
            self.set_main(self.go_btn, f"Make stills of all {plural(total, 'video')}" if total else "Make stills",
                          plural(total, "video"))

    def make(self):
        items = [i for i in (self.coll.ticked() or self.coll.items()) if Path(i["path"]).exists()]
        if not items:
            dialogs.info("Nothing to make stills of", "Add a folder of videos, or drag videos in.", icon_name="stills")
            return
        out = self._out_dir()
        settings.save({"stills_out": out or ""})
        for i in items:
            self.coll.update(i["path"], status="Queued", detail="")
        paths = [i["path"] for i in items]
        self.app.start(jobs.Job(f"Making stills of {plural(len(paths), 'video')}", self._job, paths, out,
                                short="Stills", done=lambda _j: self._made()))

    def _job(self, paths, out, log, progress):
        def state(path, status, detail):
            self.app.on_main(lambda: self.coll.update(path, status=status, detail=detail))
        try:
            made, skipped, failed = stills.make(paths, out, log, progress, state)
        finally:
            self.app.on_main(lambda: [self.coll.update(p, status="") for p in paths
                                      if (self.coll.find(p) or {}).get("status") in ("Queued", "Working")])
        folder = out or str(Path(paths[0]).parent)
        return {"summary": f"{made} made, {skipped} already had them, {failed} failed",
                "next": ("Open the stills folder", lambda: open_path(folder))}

    def _made(self):
        for item in self.coll.items():
            self.coll.model.changed(item)
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

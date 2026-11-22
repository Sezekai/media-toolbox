"""The Settings, Look and Keys screens."""
import os
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

import appearance
import dialogs
import duplicates_engine as de
import engine_ui
import fileops
import gpu
import icons
import jobs
import movelog
import paths
import preview
import settings
import theme
import thumbs
import version
import widgets
from media_utils import open_path
from widgets import (ElidedLabel, FlowLayout, Page, Segmented, button, divider, label, line_edit, muted, repolish)


class Box(QFrame):
    """A titled panel whose contents scroll up and down when it's made smaller than they are. Boxes sit in
    splitters, so each one can be made taller, shorter, wider or narrower, and the sizes are remembered."""

    def __init__(self, title, note="", min_w=240, min_h=90):
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumSize(min_w, min_h)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAD + 2, theme.PAD, 4, theme.PAD - 2)
        outer.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, theme.PAD - 2, 0)
        self.title_label = label(title, "heading")
        head.addWidget(self.title_label)
        if note:
            head.addWidget(ElidedLabel(note, "caption"), 1)
        else:
            head.addStretch(1)
        self.head = head
        outer.addLayout(head)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.v = QVBoxLayout(host)
        self.v.setContentsMargins(0, 2, theme.PAD - 2, 2)  # room for the scroll bar on the right
        self.v.setSpacing(theme.GAP)
        area.setWidget(host)
        outer.addWidget(area, 1)
        self.area = area

    def finish(self):
        self.v.addStretch(1)

    def wanted_height(self):
        """How tall the box must be to show everything without scrolling, at its current width."""
        host = self.area.widget()
        width = max(100, self.area.viewport().width())
        inner = host.heightForWidth(width) if host.hasHeightForWidth() else -1
        if inner < 0:
            inner = host.sizeHint().height()
        m = self.layout().contentsMargins()
        return inner + m.top() + m.bottom() + self.layout().spacing() + theme.text_px("title") + 12


def splitter(key, orientation, widgets_, sizes, fit=False):
    """Boxes side by side (or stacked) with handles between them; their sizes are remembered. With fit, a
    first-time stack gives each box the height its contents need, and any room left to the last one."""
    from PySide6.QtWidgets import QSplitter
    sp = QSplitter(orientation)
    sp.setChildrenCollapsible(False)
    sp.setHandleWidth(theme.GAP)
    for w in widgets_:
        sp.addWidget(w)
    for n in range(len(widgets_)):
        sp.setStretchFactor(n, 1)
    sp.setSizes(sizes)
    if fit and not widgets.remembered(key):
        def share():
            want = [w.wanted_height() if isinstance(w, Box) else w.sizeHint().height() for w in widgets_]
            room = sp.height() - sp.handleWidth() * (len(widgets_) - 1)
            if room <= 0:
                return
            if sum(want) < room:
                want[-1] += room - sum(want)
            sp.setSizes(want)
        QTimer.singleShot(0, share)
        QTimer.singleShot(150, share)  # again once the window has its real size
    widgets.remember(key, sp)
    return sp


def option(layout, title, note, *controls):
    """A setting: its name, what it does, and its control right underneath, so they read as one."""
    block = QVBoxLayout()
    block.setSpacing(3)
    block.addWidget(label(title, "value"))
    if note:
        block.addWidget(label(note, "caption", wrap=True))
    row = QHBoxLayout()
    row.setSpacing(theme.GAP)
    row.setContentsMargins(0, 3, 0, 0)
    for c in controls:
        row.addWidget(c)
    row.addStretch(1)
    block.addLayout(row)
    layout.addLayout(block)
    layout.addSpacing(6)


def group(layout, title, note=""):
    """A heading over a group of settings."""
    if layout.count():
        layout.addSpacing(12)
    head = QHBoxLayout()
    head.setContentsMargins(2, 0, 2, 2)
    head.setSpacing(10)
    head.addWidget(label(title, "heading"))
    if note:
        head.addWidget(ElidedLabel(note, "caption"), 1)
    else:
        head.addStretch(1)
    layout.addLayout(head)


class SettingRow(QFrame):
    """One setting as its own card: the name and a short note, with its controls on the same card. When the
    card is too narrow for both side by side, the controls go under the text instead of squeezing it."""
    TEXT_MIN = 240

    def __init__(self, title, note, controls, tip=None, elide=False):
        super().__init__()
        self.setObjectName("setrow")
        from PySide6.QtWidgets import QBoxLayout, QSizePolicy
        # The two columns share the width equally; a narrow card stacks its controls instead of widening.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(12, 7, 8, 7)
        self.box.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(8)
        t = label(title, "value")
        t.setStyleSheet("font-weight: 600;")
        if tip:
            t.setToolTip(tip)
            self.setToolTip(tip)
        self.title_row.addWidget(t)
        self.title_row.addStretch(1)
        text.addLayout(self.title_row)
        self.elide = elide  # an elided note (a path) can be short, so the controls stay beside it longer
        self.note = ElidedLabel(note, "caption", Qt.ElideMiddle) if elide else label(note, "caption", wrap=True)
        text.addWidget(self.note)
        self.box.addLayout(text, 1)
        self.controls = QWidget()
        ch = QHBoxLayout(self.controls)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(theme.GAP)
        for c in controls:
            ch.addWidget(c, 0, Qt.AlignVCenter)
        self.box.addWidget(self.controls, 0, Qt.AlignVCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        from PySide6.QtWidgets import QBoxLayout
        need = self.controls.sizeHint().width() + (150 if self.elide else self.TEXT_MIN) + 32
        stacked = self.width() < need
        want = QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight
        if self.box.direction() != want:
            self.box.setDirection(want)
            self.box.setAlignment(self.controls, (Qt.AlignLeft if stacked else Qt.AlignVCenter))
            self.box.setSpacing(6 if stacked else 12)


def setting(layout, title, note, *controls, tip=None, elide=False):
    """Add a SettingRow. Returns (the card, its note label)."""
    frame = SettingRow(title, note, controls, tip, elide)
    layout.addWidget(frame)
    return frame, frame.note


def buttons_row(layout, *buttons_):
    host, flow = widgets.wrap_row()
    flow._center = False
    for b in buttons_:
        flow.addWidget(b)
    layout.addWidget(host)
    return host


# ===================================================================== Settings
class SettingsPage(Page):
    title = "Settings"
    subtitle = "How the app behaves, the duplicate engine, where things are kept, and resets."
    icon = "settings"

    def build(self):
        saved = settings.load()
        area = QScrollArea()  # only scrolls when the window is too short for everything
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        cols = QHBoxLayout(host)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(theme.PAGE + 4)
        left, right = QVBoxLayout(), QVBoxLayout()
        for c in (left, right):
            c.setSpacing(4)
            cols.addLayout(c, 1)
        area.setWidget(host)
        self.body.addWidget(area, 1)

        # ----- the app -----
        group(left, "The app")
        self.click = Segmented([("select", "Selects it"), ("tick", "Ticks it")],
                               "tick" if saved.get("click_ticks") else "select")
        self.click.changed.connect(lambda val: settings.save({"click_ticks": val == "tick"}))
        setting(left, "When you click an item", "Ctrl+click and the tick box always tick.", self.click)
        self.hover = QCheckBox("On")
        self.hover.setChecked(saved.get("hover_previews", True))
        self.hover.toggled.connect(lambda on: settings.save({"hover_previews": on}))
        setting(left, "Silent previews on duplicate cards", "Play while the pointer rests on a copy. Off in safe mode."
                + ("" if preview.AVAILABLE else " Not available on this PC."), self.hover)
        self.use = Segmented([("auto", "Auto"), ("gpu", "GPU"), ("cpu", "CPU")], saved.get("gpu_use", "auto"))
        self.use.changed.connect(self._gpu_changed)
        _f, self.gpu_found = setting(left, "Decode duplicate scans on", "Looking for a GPU\u2026", self.use)

        # ----- the engine -----
        group(left, "Duplicate engine")
        self.install_btn = button("Install engine\u2026")
        self.install_btn.clicked.connect(lambda: engine_ui.install(self.app))
        self.update_btn = button("Check for an update")
        self.update_btn.clicked.connect(lambda: engine_ui.install(self.app, update=True))
        self.ffmpeg_btn = button("Get FFmpeg\u2026")
        self.ffmpeg_btn.clicked.connect(lambda: engine_ui.install_ffmpeg(self.app))
        _f, self.engine_status = setting(left, "vdf-cli (AGPL)", "", self.install_btn, self.update_btn,
                                         self.ffmpeg_btn)
        diag = button("Diagnose", icon=icons.icon("wrench", theme.TEXT, 16))
        diag.clicked.connect(self.diagnose)
        rep = button("Repair")
        rep.clicked.connect(self.repair)
        copy = button("Copy report", icon=icons.icon("copy", theme.TEXT, 16), tip="Also saved in the logs folder")
        copy.clicked.connect(self.copy_report)
        setting(left, "Checks", "Diagnose checks what the app needs; Repair fixes what's safe to fix.", diag, rep,
                copy)
        self.findings_frame = QFrame()
        self.findings_frame.setObjectName("setrow")
        self.findings_host = QVBoxLayout(self.findings_frame)
        self.findings_host.setContentsMargins(12, 8, 12, 8)
        self.findings_host.setSpacing(4)
        self.findings_frame.hide()
        left.addWidget(self.findings_frame)
        self.findings = []
        engine_ui.on_change(self.refresh_engine)

        # ----- gallery-dl -----
        group(left, "Downloads (gallery-dl)")
        own = button("Use my gallery-dl.exe\u2026")
        own.clicked.connect(lambda: __import__("gdl_ui").pick_own(self.app))
        self.gdl_btn = button("Download it\u2026")
        self.gdl_btn.clicked.connect(lambda: __import__("gdl_ui").install(self.app, update=True))
        _f, self.gdl_status = setting(left, "gallery-dl (GPL)", "", own, self.gdl_btn, elide=True)
        __import__("gdl_ui").on_change(self.refresh_gdl)

        # ----- updates -----
        group(left, "Updates")
        self.auto_update = QCheckBox("Check once a day")
        self.auto_update.setChecked(saved.get("check_updates", True))
        self.auto_update.toggled.connect(lambda on: settings.save({"check_updates": on}))
        check_btn = button("Check now")
        check_btn.clicked.connect(lambda: __import__("update_ui").check(self.app))
        _f, self.update_note = setting(left, f"Version {version.__version__}",
                                       "Updates download inside the app, so Windows doesn't stop them with a "
                                       "\u201cprotected your PC\u201d warning.", self.auto_update, check_btn)

        # ----- about -----
        group(left, "About")
        logs_btn = button("Open the logs folder", icon=icons.icon("folder", theme.TEXT, 16))
        logs_btn.clicked.connect(lambda: open_path(paths.logs_dir()))
        setting(left, f"Media Toolbox {version.__version__}", "One portable program. FFmpeg is bundled.", logs_btn)
        left.addStretch(1)

        # ----- storage -----
        group(right, "Storage", "Move any place to another drive. The old copy goes to the Recycle Bin once the "
              "new one is checked.")
        self.storage_host = QVBoxLayout()
        self.storage_host.setSpacing(4)
        right.addLayout(self.storage_host)
        self.size_labels = {}
        self._fill_storage()

        # ----- reset -----
        group(right, "Reset", "Each asks first. Nothing here touches your videos or pictures.")
        for title, note, fn in (
                ("Settings and sizes", "Choices, folder lists, box, column and window sizes. The look and storage "
                 "places stay.", self.reset_settings),
                ("Checked videos and ignored groups", "Lets them come back in duplicate scans.", self.reset_dups),
                ("Move log", "Moves already made can't be undone afterwards.", self.reset_moves)):
            b = button("Reset\u2026", "danger-ghost")
            b.clicked.connect(fn)
            setting(right, title, note, b)
        right.addStretch(1)
        self.refresh_engine()

    def refresh_gdl(self):
        import gdl_engine as ge
        exe = ge.find_exe()
        if exe is None:
            self.gdl_status.setText("Not set up. The Downloads tool needs it.")
            self.gdl_btn.setText("Download it\u2026")
        else:
            self.gdl_status.setText(f"{ge.version(exe) or 'unknown version'} \u00b7 {exe}")
            self.gdl_btn.setText("Check for an update")
        self.gdl_status.setToolTip(str(exe or ""))

    def show_update(self, info):
        if info["newer"]:
            self.update_note.setText(f"Media Toolbox {info['version']} is available.")
        else:
            self.update_note.setText(f"You have the newest version. Checked just now.")

    def shown(self):
        self.refresh_engine()
        self.refresh_gdl()
        self._refresh_sizes()
        threading.Thread(target=self._detect_gpu, daemon=True).start()

    # ----- GPU -----
    def _gpu_changed(self, value):
        settings.save({"gpu_use": value})
        threading.Thread(target=self._detect_gpu, daemon=True).start()

    def _detect_gpu(self):
        card = gpu.detect()
        use, reason = gpu.use_gpu()
        text = (f"Found {card['name']} (driver {card['driver']}). " if card else "") + reason
        self.app.on_main(lambda: self.gpu_found.setText(text))

    # ----- engine -----
    def refresh_engine(self):
        engine = de.find_engine()
        ver = de.installed_version()
        if engine:
            self.engine_status.setText(f"Installed{f' (version {ver})' if ver else ''} in {Path(engine).parent}")
            self.install_btn.setText("Install again\u2026")
        else:
            self.engine_status.setText("Not installed. Duplicate finding needs it.")
            self.install_btn.setText("Install engine\u2026")
        self.update_btn.setVisible(bool(engine))
        ok, text = de.ffmpeg_ready()
        if not ok:
            self.engine_status.setText(self.engine_status.text_full() + f" FFmpeg for it: {text}.")
        self.ffmpeg_btn.setVisible(not ok)
        self.app.set_attention("dup", not engine)

    def diagnose(self):
        import diagnose
        self.app.start(jobs.Job("Diagnosing", diagnose.run, short="Diagnosing", done=self._diagnosed))

    def _diagnosed(self, job):
        if job.finished != "done":
            return
        self.findings = job.result
        while self.findings_host.count():
            w = self.findings_host.takeAt(0).widget()
            if w:
                w.deleteLater()
        for f in self.findings:
            self.findings_host.addWidget(Finding(f))
        self.findings_frame.setVisible(bool(self.findings))
        bad = sum(1 for f in self.findings if f["kind"] != "ok")
        self.app.toast("Everything checked out." if not bad else f"{bad} thing(s) need a look.",
                       "ok" if not bad else "warn")

    def repair(self):
        import diagnose
        if not dialogs.ask("Repair?", "Empties the temporary folder, makes missing folders, removes unfinished "
                           "downloads and copies the bundled FFmpeg again. Your files aren't touched.", "Repair"):
            return
        self.app.start(jobs.Job("Repairing", lambda log, progress: {"summary": "; ".join(diagnose.repair(log)) or
                                                                    "nothing needed"}, short="Repairing",
                                done=lambda j: (self.diagnose() if j.finished == "done" else None)))

    def copy_report(self):
        import diagnose
        if not self.findings:
            self.app.start(jobs.Job("Diagnosing", diagnose.run, short="Diagnosing",
                                    done=lambda j: (self._diagnosed(j), self.copy_report()) if j.finished == "done"
                                    else None))
            return
        QGuiApplication.clipboard().setText(diagnose.report(self.findings))
        self.app.toast("Copied the report. It's also saved in the logs folder.", "ok")

    # ----- storage -----
    def _fill_storage(self):
        while self.storage_host.count():
            w = self.storage_host.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.size_labels = {}
        for place in paths.PLACES:
            open_b = button("Open", tip="Open this folder")
            open_b.clicked.connect(lambda _c=False, p=place: open_path(paths.place(p.key)))
            move_b = button("Move\u2026", tip="Move it to another folder or drive")
            move_b.clicked.connect(lambda _c=False, p=place: self.move_place(p))
            clear_b = button("Clear", tip="Delete these files. They're made again when needed.")
            clear_b.clicked.connect(lambda _c=False, p=place: self.clear_place(p))
            for b, w in ((open_b, 70), (move_b, 80), (clear_b, 70)):
                b.setFixedWidth(w)  # the same buttons line up from row to row
            if not place.cache:
                sp = clear_b.sizePolicy()
                sp.setRetainSizeWhenHidden(True)
                clear_b.setSizePolicy(sp)
                clear_b.hide()
            missing = place.missing()
            size = label("Working out\u2026", "caption")
            size.setFixedWidth(118)
            size.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            frame, note = setting(self.storage_host, place.title, "", size, open_b, move_b, clear_b, tip=place.note,
                                  elide=True)
            note.setText(str(place.path()) + ("  (drive not connected)" if missing else ""))
            note.setProperty("role", "danger" if missing else "mono")
            repolish(note)
            self.size_labels[place.key] = size

    def _refresh_sizes(self):
        for lab in self.size_labels.values():
            lab.setText("Working out\u2026")

        def worker():
            for place in paths.PLACES:
                path = place.path()
                text = "drive missing" if place.missing() else (
                    "{} \u00b7 {} files".format(*(lambda s: (fileops.human_size(s[0]), s[1]))(paths.folder_size(path)))
                    if path.exists() else "empty")
                self.app.on_main(lambda k=place.key, t=text: self.size_labels.get(k) and self.size_labels[k].setText(t))
        threading.Thread(target=worker, daemon=True).start()

    def clear_place(self, place):
        size, count = paths.folder_size(place.path()) if place.path().exists() else (0, 0)
        if not dialogs.ask(f"Clear {place.title.lower()}?", f"{count} files ({fileops.human_size(size)}) in "
                           f"{place.path()}. They're the app's own and are made again when needed.",
                           f"Clear {fileops.human_size(size)}", kind="danger"):
            return

        def job(log, progress):
            folder = place.path()
            for n, child in enumerate(list(folder.iterdir()) if folder.exists() else []):
                progress(n, 0, f"Clearing {child.name}")
                try:
                    shutil.rmtree(child) if child.is_dir() else child.unlink()  # cache files only
                except OSError as exc:
                    log(f"Couldn't remove {child}: {exc}")
            return {"summary": f"{fileops.human_size(size)} cleared"}
        if place.key == "thumbs":
            thumbs.shared().forget()
        self.app.start(jobs.Job(f"Clearing {place.title.lower()}", job, short="Clearing",
                                done=lambda _j: self._refresh_sizes()))

    def move_place(self, place):
        if self.app.queue.busy():
            dialogs.info("Wait for the running job", "Places can be moved when nothing is running.", icon_name="info")
            return
        chosen = QFileDialog.getExistingDirectory(self, f"Move {place.title.lower()} into")
        if not chosen:
            return
        old = place.path()
        name = "Media Toolbox" if place.key == "data" else old.name
        target = Path(chosen) / name
        if target.resolve() == old.resolve() if old.exists() else False:
            return
        size, count = paths.folder_size(old) if old.exists() else (0, 0)
        if target.exists() and any(target.iterdir()):
            dialogs.error("That folder isn't empty", f"{target} already has files in it. Choose another place.")
            return
        if not dialogs.ask(f"Move {place.title.lower()}?", f"{count} files ({fileops.human_size(size)}) are copied, "
                           "checked, and the app switches to the new place. The old copy then goes to the Recycle "
                           "Bin.", f"Move {fileops.human_size(size)}", items=[(str(old), "from"), (str(target), "to")]):
            return
        self.app.start(jobs.Job(f"Moving {place.title.lower()}", self._move_job, place.key, old, target,
                                short="Moving storage", done=lambda _j: (self._fill_storage(), self._refresh_sizes())))

    def _move_job(self, key, old, target, log, progress):
        files = []
        for dirpath, _dirs, names in os.walk(old) if old.exists() else []:
            for n in names:
                files.append(Path(dirpath) / n)
        total = sum(f.stat().st_size for f in files)
        done = 0
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            dst = target / f.relative_to(old)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            if dst.stat().st_size != f.stat().st_size:
                raise RuntimeError(f"{dst} didn't copy fully. Nothing was switched; the old place is still used.")
            done += f.stat().st_size
            progress(done, total, f"Copying {f.name}", size=True)
        # switch
        if key == "data":
            pointer = paths.default_data_dir() / paths.POINTER
            paths.ensure(pointer.parent)
            fileops.write_json(pointer, {"data": str(target)})
        else:
            storage = dict(settings.load().get("storage", {}))
            storage[key] = str(target)
            settings.save({"storage": storage})
        log(f"Switched to {target}.")
        if old.exists():
            try:
                fileops.recycle(old)
                log(f"Sent the old copy {old} to the Recycle Bin.")
            except fileops.RecycleError as exc:
                log(f"{exc} You can delete the old copy yourself: {old}")
        return {"summary": f"moved to {target}"}

    # ----- reset -----
    def reset_settings(self):
        if not dialogs.ask("Reset settings and sizes?", "Choices, folder lists, column widths and the window size go "
                           "back to how they started. Takes effect when the app next starts.", "Reset settings",
                           kind="danger"):
            return
        keep = ("storage", "dup_engine_version", "dup_ignored", "dup_files_done", "dup_last_files")
        settings.reset(keep=keep)
        widgets.reset_remembered()
        self.app.reset_on_close = True
        self.app.toast("Settings reset. Restart the app to see every change.", "ok")

    def reset_dups(self):
        if not dialogs.ask("Forget checked videos and ignored groups?", "Ignored groups can show up again, and "
                           "videos already checked against the library are ticked again.", "Forget them",
                           kind="danger"):
            return
        settings.save({"dup_ignored": [], "dup_files_done": {}})
        de.save_results("library", [])
        de.save_results("folder", [])
        self.app.toast("Done. The next scan shows everything again.", "ok")

    def reset_moves(self):
        n = len(movelog.entries())
        if not dialogs.ask("Clear the move log?", f"{n} logged move(s) are forgotten and can't be undone after this.",
                           "Clear the move log", kind="danger"):
            return
        movelog.clear()
        self.app.toast("The move log is empty.", "ok")


class Finding(QFrame):
    """One finding: an icon, a title, the evidence, and what fixes it."""

    def __init__(self, f):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        ic = QLabel()
        name, colour = {"ok": ("check", theme.OK), "warn": ("warn", theme.WARN), "error": ("error", theme.DANGER)}[
            f["kind"]]
        ic.setPixmap(icons.pixmap(name, colour, 16))
        h.addWidget(ic, 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(1)
        v.addWidget(label(f["title"], "value"))
        v.addWidget(ElidedLabel(f["evidence"], "caption", Qt.ElideMiddle))
        if f["fix"]:
            v.addWidget(label("Fix: " + f["fix"], "muted", wrap=True))
        h.addLayout(v, 1)


# ===================================================================== Look
class Swatch(QAbstractButton):
    """A preset tile: a sample of the colours, the name under it."""

    def __init__(self, colours, name, round_=False, size=34, width=None):
        super().__init__()
        self.setObjectName("swatch")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)
        self.setFixedSize(width or size + 52, size + 28)
        self.setFocusPolicy(Qt.TabFocus)
        self.colours, self.name, self.round_, self.size_ = colours, name, round_, size

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, theme.R_CONTROL, theme.R_CONTROL)
        if self.isChecked() or self.underMouse() or self.hasFocus():
            p.fillPath(path, QColor(theme.RAISED))
        p.setPen(QPen(QColor(theme.OUTLINE if self.isChecked() or self.hasFocus() else theme.LINE),
                      2 if self.isChecked() or self.hasFocus() else 1))
        p.drawPath(path)
        x = (self.width() - self.size_) // 2
        p.drawPixmap(x, 4, icons.swatch_pixmap(self.colours, self.size_, self.round_))
        p.setPen(QColor(theme.TEXT if self.isChecked() else theme.SEC))
        p.setFont(theme.font("caption"))
        p.drawText(self.rect().adjusted(2, self.size_ + 6, -2, -2), Qt.AlignHCenter | Qt.AlignTop,
                   p.fontMetrics().elidedText(self.name, Qt.ElideRight, self.width() - 6))
        p.end()


class ColourButton(QPushButton):
    def __init__(self, colour, on_pick, title):
        super().__init__()
        self.on_pick, self.title = on_pick, title
        self.setFixedSize(26, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self.set_colour(colour)

    def set_colour(self, colour):
        self.colour = colour
        self.setStyleSheet(f"QPushButton {{ background: {colour}; border: 1px solid {theme.LINE2}; "
                           f"border-radius: 4px; min-height: 20px; max-height: 20px; padding: 0px; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.colour), self, self.title)
        if c.isValid():
            self.on_pick(c.name())


class LookPage(Page):
    title = "Look"
    subtitle = "Background, accent, font, corners and spacing. Changes show straight away; save them as a theme."
    icon = "look"

    def build(self):
        self.store = appearance.load_store()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(150)
        self._save_timer.timeout.connect(self._apply_now)
        # ----- themes -----
        themes = Box("Themes", min_w=220, min_h=160)
        tv = themes.v
        self.theme_list = QListWidget()
        self.theme_list.setItemDelegate(widgets.TintDelegate(self.theme_list))
        self.theme_list.itemClicked.connect(self._pick_theme)
        self.theme_list.setMinimumHeight(60)
        tv.addWidget(self.theme_list, 1)
        self.active_note = label("", "caption", wrap=True)
        tv.addWidget(self.active_note)
        acts = [("Save as theme\u2026", self.save_as), ("Update", self.update_theme), ("Rename\u2026", self.rename),
                ("Duplicate", self.duplicate), ("Export\u2026", self.export), ("Import\u2026", self.import_),
                ("Delete\u2026", self.delete), ("Reset to default", self.reset_default)]
        self.theme_buttons = {}
        made = []
        for n, (text, fn) in enumerate(acts):
            kind = "primary" if n == 0 else "danger-ghost" if text.startswith("Delete") else (
                "ghost" if text.startswith("Reset") else "secondary")
            b = button(text, kind)
            b.clicked.connect(fn)
            self.theme_buttons[text] = b
            made.append(b)
        buttons_row(tv, *made)
        preview_box = Box("Preview", min_w=220, min_h=120)
        self._preview(preview_box.v)
        preview_box.finish()

        bg_box = Box("Background", min_h=110)
        bg_v = bg_box.v
        self.bg_tiles = {}
        bg_host = QWidget()
        bg_flow = FlowLayout(bg_host, spacing=6, vspacing=6)
        for key, b in appearance.BACKGROUNDS.items():
            s = Swatch([b["panel"], b["raised2"], b["text"]], b["name"], size=30)
            s.clicked.connect(lambda _c=False, k=key: self._set_background(k))
            bg_flow.addWidget(s)
            self.bg_tiles[key] = s
        bg_v.addWidget(bg_host)
        self.edit_colours = QCheckBox("Edit each colour")
        bg_v.addWidget(self.edit_colours)
        self.colour_grid_host = QWidget()
        cg = QGridLayout(self.colour_grid_host)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setHorizontalSpacing(8)
        cg.setVerticalSpacing(4)
        self.colour_buttons, self.hex_edits = {}, {}
        entries = [("background", k, t) for k, t in appearance.BG_LABELS] + \
                  [("states", k, t) for k, t in appearance.STATE_LABELS]
        for n, (part, key, title) in enumerate(entries):
            r, c = n // 3, (n % 3) * 3
            cb = ColourButton("#000000", lambda colour, p=part, k=key: self._set_colour(p, k, colour), title)
            hx = line_edit(width=78, mono=True)
            hx.editingFinished.connect(lambda p=part, k=key, e=hx: self._set_colour(p, k, e.text()))
            cg.addWidget(cb, r, c)
            cg.addWidget(hx, r, c + 1)
            cg.addWidget(label(title, "caption"), r, c + 2)
            self.colour_buttons[(part, key)] = cb
            self.hex_edits[(part, key)] = hx
        self.colour_grid_host.setVisible(False)
        self.edit_colours.toggled.connect(self.colour_grid_host.setVisible)
        bg_v.addWidget(self.colour_grid_host)

        bg_box.finish()
        ac_box = Box("Accent", min_h=110)
        ac_v = ac_box.v
        self.acc_tiles = {}
        acc_host = QWidget()
        acc_flow = FlowLayout(acc_host, spacing=6, vspacing=6)
        for key, a in appearance.ACCENTS.items():
            s = Swatch(a["stops"], a["name"], round_=True, size=26, width=104)
            s.clicked.connect(lambda _c=False, k=key: self._set_accent(appearance.ACCENTS[k]["stops"]))
            acc_flow.addWidget(s)
            self.acc_tiles[key] = s
        ac_v.addWidget(acc_host)
        stops_row = QHBoxLayout()
        stops_row.setSpacing(6)
        stops_row.addWidget(muted("Colours"))
        self.stop_buttons = []
        for n in range(4):
            cb = ColourButton("#000000", lambda colour, i=n: self._set_stop(i, colour), f"Accent colour {n + 1}")
            self.stop_buttons.append(cb)
            stops_row.addWidget(cb)
        self.add_stop = button("Add", "ghost", tip="Add a colour (up to 4)")
        self.add_stop.clicked.connect(self._add_stop)
        self.remove_stop = button("Remove", "ghost", tip="Remove the last colour")
        self.remove_stop.clicked.connect(self._remove_stop)
        stops_row.addWidget(self.add_stop)
        stops_row.addWidget(self.remove_stop)
        stops_row.addSpacing(12)
        stops_row.addWidget(muted("Angle"))
        self.angle = QSlider(Qt.Horizontal)
        self.angle.setRange(0, 360)
        self.angle.setFixedWidth(140)
        self.angle.valueChanged.connect(self._set_angle)
        stops_row.addWidget(self.angle)
        self.angle_label = label("", "caption")
        self.angle_label.setFixedWidth(34)
        stops_row.addWidget(self.angle_label)
        stops_row.addStretch(1)
        ac_v.addLayout(stops_row)
        on_row = QHBoxLayout()
        on_row.addWidget(muted("Text on the accent"))
        self.on_accent = Segmented([("auto", "Auto"), ("dark", "Dark"), ("light", "Light")])
        self.on_accent.changed.connect(self._set_on_accent)
        on_row.addWidget(self.on_accent)
        self.contrast = label("", "caption")
        on_row.addWidget(self.contrast)
        on_row.addStretch(1)
        ac_v.addLayout(on_row)

        ac_box.finish()
        ft_box = Box("Font", min_h=90)
        ft_v = ft_box.v
        font_row = QHBoxLayout()
        font_row.setSpacing(theme.GAP)
        self.font_box = QComboBox()
        self.font_box.setMinimumWidth(240)
        self.font_box.currentIndexChanged.connect(self._font_picked)
        font_row.addWidget(self.font_box)
        add_font = button("Add font\u2026", icon=icons.icon("folder_plus", theme.TEXT, 16),
                          tip="Copy .ttf or .otf files into the app so the font works on any PC")
        add_font.clicked.connect(self.add_font)
        font_row.addWidget(add_font)
        font_row.addSpacing(12)
        font_row.addWidget(muted("Text size"))
        self.text_size = Segmented([(s, f"{s}") for s in appearance.TEXT_SIZES])
        self.text_size.changed.connect(lambda s: self._set("font", "size", s))
        font_row.addWidget(self.text_size)
        font_row.addStretch(1)
        ft_v.addLayout(font_row)

        ft_box.finish()
        sh_box = Box("Shape and spacing", min_h=110)
        sh_v = sh_box.v
        self.corners = Segmented([(k, c["name"]) for k, c in appearance.CORNERS.items()])
        self.corners.changed.connect(lambda k: self._set_pair("corners", appearance.CORNERS[k]))
        self.c_control = self._slider(0, 16, lambda val: self._set("corners", "control", val))
        self.c_panel = self._slider(0, 24, lambda val: self._set("corners", "panel", val))
        self._shape_row(sh_v, "Corners", self.corners, [("Controls", self.c_control), ("Panels", self.c_panel)])
        self.density = Segmented([(k, d["name"]) for k, d in appearance.DENSITY.items()])
        self.density.changed.connect(lambda k: self._set_pair("density", appearance.DENSITY[k]))
        self.d_control = self._slider(24, 44, lambda val: self._set("density", "control", val))
        self.d_row = self._slider(20, 40, lambda val: self._set("density", "row", val))
        self._shape_row(sh_v, "Density", self.density, [("Controls", self.d_control), ("List rows", self.d_row)])
        self.buttons_style = Segmented([("flat", "Flat"), ("glow", "Glow")])
        self.buttons_style.changed.connect(lambda s: self._set("buttons", "style", s))
        self._shape_row(sh_v, "Main buttons", self.buttons_style, [])
        sh_box.finish()
        ol_box = Box("Outline and highlight", min_h=90)
        ol_v = ol_box.v
        ol_v.addWidget(label("The outline marks what's selected or has the keyboard's focus. The highlight is the "
                             "tint behind selected and ticked items.", "caption", wrap=True))
        self.outline_colour = ColourButton("#000000", lambda c: self._set("outline", "colour", c), "Outline colour")
        self.outline_accent = button("Use the accent", "ghost")
        self.outline_accent.clicked.connect(lambda: self._set("outline", "colour", ""))
        self.outline_width = Segmented([(n, f"{n}px") for n in (1, 2, 3, 4)])
        self.outline_width.changed.connect(lambda n: self._set("outline", "width", n))
        row = QHBoxLayout()
        row.setSpacing(theme.GAP)
        t1 = muted("Outline")
        t1.setFixedWidth(theme.LABEL_W)
        row.addWidget(t1)
        row.addWidget(self.outline_colour)
        row.addWidget(self.outline_accent)
        row.addSpacing(12)
        row.addWidget(label("Width", "caption"))
        row.addWidget(self.outline_width)
        row.addStretch(1)
        ol_v.addLayout(row)
        self.highlight_colour = ColourButton("#000000", lambda c: self._set("highlight", "colour", c),
                                             "Highlight colour")
        self.highlight_accent = button("Use the accent", "ghost")
        self.highlight_accent.clicked.connect(lambda: self._set("highlight", "colour", ""))
        row = QHBoxLayout()
        row.setSpacing(theme.GAP)
        t2 = muted("Highlight")
        t2.setFixedWidth(theme.LABEL_W)
        row.addWidget(t2)
        row.addWidget(self.highlight_colour)
        row.addWidget(self.highlight_accent)
        row.addStretch(1)
        ol_v.addLayout(row)
        ol_box.finish()
        left = splitter("look_left", Qt.Vertical, [themes, preview_box], [380, 330], fit=True)
        right = splitter("look_right", Qt.Vertical, [bg_box, ac_box, ft_box, sh_box, ol_box],
                         [190, 250, 110, 220, 110],
                         fit=True)
        self.body.addWidget(splitter("look_cols", Qt.Horizontal, [left, right], [280, 1000]), 1)
        self._load_fonts()
        self._show()

    # ----- building helpers -----
    def _slider(self, low, high, fn):
        s = QSlider(Qt.Horizontal)
        s.setRange(low, high)
        s.setFixedWidth(110)
        s.valueChanged.connect(lambda val: None if getattr(self, "_showing", False) else fn(val))
        return s

    def _shape_row(self, layout, title, seg, sliders):
        row = QHBoxLayout()
        row.setSpacing(theme.GAP)
        t = muted(title)
        t.setFixedWidth(theme.LABEL_W)
        row.addWidget(t)
        row.addWidget(seg)
        row.addStretch(1)
        layout.addLayout(row)
        if not sliders:
            return
        fine = QHBoxLayout()
        fine.setSpacing(theme.GAP)
        fine.addSpacing(theme.LABEL_W + theme.GAP)
        for name, s in sliders:
            lab = label(name, "caption")
            lab.setFixedWidth(64)
            fine.addWidget(lab)
            fine.addWidget(s)
            val = label("", "caption")
            val.setFixedWidth(34)
            s.valueChanged.connect(lambda x, v=val: v.setText(f"{x}px"))
            fine.addWidget(val)
            fine.addSpacing(10)
        fine.addStretch(1)
        layout.addLayout(fine)

    def _preview(self, v):
        b = QHBoxLayout()
        b.addWidget(button("Convert", "primary"))
        b.addWidget(button("Browse"))
        b.addStretch(1)
        v.addLayout(b)
        v.addWidget(line_edit("D:\\Videos\\Clips"))
        lst = QListWidget()
        lst.setItemDelegate(widgets.TintDelegate(lst))
        for n, t in enumerate(("holiday.mp4", "concert.mkv", "interview.mov")):
            it = QListWidgetItem(t)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if n == 1 else Qt.Unchecked)
            lst.addItem(it)
        lst.setCurrentRow(0)
        lst.setFixedHeight(3 * theme.ROW_H + 8)
        self.preview_list = lst
        v.addWidget(lst)
        tags = QHBoxLayout()
        for text, kind in (("Best copy", "acc"), ("Done", "ok"), ("Failed", "danger")):
            tags.addWidget(widgets.tag(text, kind))
        tags.addStretch(1)
        v.addLayout(tags)
        from PySide6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setValue(64)
        bar.setTextVisible(False)
        v.addWidget(bar)

    # ----- fonts -----
    def _load_fonts(self):
        self._showing = True
        self.font_box.blockSignals(True)
        self.font_box.clear()
        installed = set(QFontDatabase.families())
        for entry in appearance.bundled_fonts():
            if entry.get("mono"):
                continue
            self.font_box.addItem(entry["family"], entry["family"])
            self.font_box.setItemData(self.font_box.count() - 1, QFont(entry["family"], 11), Qt.FontRole)
        for entry in appearance.added_fonts():
            self.font_box.addItem(f"{entry['family']} (added)", entry["family"])
            self.font_box.setItemData(self.font_box.count() - 1, QFont(entry["family"], 11), Qt.FontRole)
        self.font_box.insertSeparator(self.font_box.count())
        for fam in appearance.SYSTEM_FONTS:
            ok = fam in installed
            self.font_box.addItem(f"{fam} ({'installed' if ok else 'not installed'})", fam)
            idx = self.font_box.count() - 1
            if ok:
                self.font_box.setItemData(idx, QFont(fam, 11), Qt.FontRole)
            else:
                self.font_box.model().item(idx).setEnabled(False)
        self.font_box.blockSignals(False)
        self._showing = False

    def _font_picked(self, _i):
        fam = self.font_box.currentData()
        if fam and not self._showing:
            self._set("font", "family", fam)

    def add_font(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose font files", "", "Fonts (*.ttf *.otf)")
        if not files:
            return
        guess, _w = appearance.guess_font(files)
        name = dialogs.get_text("Name this font", f"{len(files)} file(s). The name shows in the font list.", guess,
                                "Add font")
        if not name:
            return
        entry = appearance.add_font(name, files)
        for f in entry["files"]:
            QFontDatabase.addApplicationFont(str(paths.fonts_dir() / entry["id"] / f["file"]))
        self._load_fonts()
        self._set("font", "family", name)
        self.app.toast(f"Added {name}.", "ok")

    # ----- changing the look -----
    @property
    def cur(self):
        return self.store["current"]

    def _changed(self):
        self.store["active"] = next((t["name"] for t in [appearance.DEFAULT_THEME] + self.store["saved"]
                                     if appearance.same_look(t, self.cur)), None)
        self._save_timer.start()
        self._show()

    def _apply_now(self):
        theme.use(self.cur)
        theme.apply(QApplication.instance())
        appearance.save_store(self.store)

    def _set(self, part, key, value):
        self.cur[part][key] = value
        self.store["current"] = appearance.normalize(self.cur)
        self._changed()

    def _set_pair(self, part, preset):
        self.cur[part] = {k: preset[k] for k in self.cur[part]}
        self._changed()

    def _set_background(self, key):
        self.store["current"] = appearance.with_background(self.cur, key)
        self._changed()

    def _set_colour(self, part, key, colour):
        self.cur[part][key] = colour
        self.store["current"] = appearance.normalize(self.cur)
        self._changed()

    def _set_accent(self, stops):
        self.cur["accent"]["stops"] = list(stops)
        self._changed()

    def _set_stop(self, i, colour):
        stops = list(self.cur["accent"]["stops"])
        if i < len(stops):
            stops[i] = colour
            self._set_accent(stops)

    def _add_stop(self):
        stops = list(self.cur["accent"]["stops"])
        if len(stops) < 4:
            self._set_accent(stops + [stops[-1]])

    def _remove_stop(self):
        stops = list(self.cur["accent"]["stops"])
        if len(stops) > 1:
            self._set_accent(stops[:-1])

    def _set_angle(self, value):
        if not getattr(self, "_showing", False):
            self.angle_label.setText(f"{value}\u00b0")
            self._set("accent", "angle", value)

    def _set_on_accent(self, value):
        self._set("accent", "onAccent", value)

    def _show(self):
        """Show the current look in the controls."""
        self._showing = True
        t = self.cur
        d = appearance.describe(t)
        for k, s in self.bg_tiles.items():
            s.setChecked(k == d["background"])
        for k, s in self.acc_tiles.items():
            s.setChecked(k == d["accent"])
        for (part, key), cb in self.colour_buttons.items():
            cb.set_colour(t[part][key])
            self.hex_edits[(part, key)].setText(t[part][key])
        stops = t["accent"]["stops"]
        for n, cb in enumerate(self.stop_buttons):
            cb.setVisible(n < len(stops))
            if n < len(stops):
                cb.set_colour(stops[n])
        self.add_stop.setEnabled(len(stops) < 4)
        self.remove_stop.setEnabled(len(stops) > 1)
        self.angle.setValue(t["accent"]["angle"])
        self.angle_label.setText(f"{t['accent']['angle']}\u00b0")
        self.on_accent.set_value(t["accent"]["onAccent"])
        ratio = appearance.on_accent_contrast(t)
        self.contrast.setText(f"Contrast {ratio:.1f}:1" + ("  \u00b7 hard to read, below 4.5:1" if ratio < 4.5 else ""))
        self.contrast.setProperty("role", "warn" if ratio < 4.5 else "caption")
        repolish(self.contrast)
        idx = self.font_box.findData(t["font"]["family"])
        if idx >= 0:
            self.font_box.setCurrentIndex(idx)
        self.text_size.set_value(t["font"]["size"])
        self.corners.set_value(d["corners"])
        self.c_control.setValue(t["corners"]["control"])
        self.c_panel.setValue(t["corners"]["panel"])
        self.density.set_value(d["density"])
        self.d_control.setValue(t["density"]["control"])
        self.d_row.setValue(t["density"]["row"])
        self.buttons_style.set_value(t["buttons"]["style"])
        self.outline_colour.set_colour(t["outline"]["colour"] or theme.ACCENT)
        self.outline_accent.setVisible(bool(t["outline"]["colour"]))
        self.outline_width.set_value(t["outline"]["width"])
        self.highlight_colour.set_colour(t["highlight"]["colour"] or theme.ACCENT)
        self.highlight_accent.setVisible(bool(t["highlight"]["colour"]))
        self._fill_themes()
        self._showing = False

    # ----- themes -----
    def _fill_themes(self):
        self.theme_list.clear()
        active = self.store.get("active")
        for t in [appearance.DEFAULT_THEME] + self.store["saved"]:
            it = QListWidgetItem(t["name"])
            it.setData(Qt.UserRole, t["name"])
            it.setToolTip(appearance.describe(t)["text"])
            it.setIcon(icons.icon("check", theme.ACCENT, 14) if t["name"] == active else icons.icon("look", theme.FAINT,
                                                                                                  14))
            self.theme_list.addItem(it)
        is_saved = active not in (None, "Default")
        self.active_note.setText(appearance.describe(self.cur)["text"] + (
            "" if active else "  \u00b7 unsaved changes"))
        selected = self._selected_theme()
        own = selected is not None and selected["name"] != "Default"
        for text in ("Rename\u2026", "Delete\u2026", "Update"):
            self.theme_buttons[text].setEnabled(own)
        _ = is_saved

    def _selected_theme(self):
        item = self.theme_list.currentItem()
        name = item.data(Qt.UserRole) if item else self.store.get("active")
        if name == "Default":
            return appearance.DEFAULT_THEME
        return next((t for t in self.store["saved"] if t["name"] == name), None)

    def _pick_theme(self, item):
        t = self._selected_theme()
        if t is None:
            return
        self.store["current"] = appearance.normalize(dict(t))
        self._changed()
        for i in range(self.theme_list.count()):
            if self.theme_list.item(i).data(Qt.UserRole) == t["name"]:
                self.theme_list.setCurrentRow(i)

    def _unique_name(self, name):
        taken = {t["name"] for t in self.store["saved"]} | {"Default"}
        if name not in taken:
            return name
        n = 2
        while f"{name} ({n})" in taken:
            n += 1
        return f"{name} ({n})"

    def save_as(self):
        name = dialogs.get_text("Save this look as a theme", "", "My theme", "Save theme")
        if not name:
            return
        t = appearance.normalize(dict(self.cur, name=self._unique_name(name)))
        self.store["saved"].append(t)
        self.store["current"] = appearance.normalize(dict(self.cur, name=t["name"]))
        self._changed()

    def update_theme(self):
        t = self._selected_theme()
        if not t or t["name"] == "Default":
            return
        if not dialogs.ask(f"Update {t['name']}?", "It's replaced with the look you have now.", "Update theme"):
            return
        self.store["saved"] = [appearance.normalize(dict(self.cur, name=t["name"])) if s["name"] == t["name"] else s
                               for s in self.store["saved"]]
        self._changed()

    def rename(self):
        t = self._selected_theme()
        if not t or t["name"] == "Default":
            return
        name = dialogs.get_text("Rename the theme", "", t["name"], "Rename")
        if not name or name == t["name"]:
            return
        name = self._unique_name(name)
        for s in self.store["saved"]:
            if s["name"] == t["name"]:
                s["name"] = name
        self._changed()

    def duplicate(self):
        t = self._selected_theme() or self.cur
        self.store["saved"].append(appearance.normalize(dict(t, name=self._unique_name(t["name"] + " copy"))))
        self._changed()

    def delete(self):
        t = self._selected_theme()
        if not t or t["name"] == "Default":
            return
        if not dialogs.ask(f"Delete the theme {t['name']}?", "Your current look stays as it is.", "Delete theme",
                           kind="danger"):
            return
        self.store["saved"] = [s for s in self.store["saved"] if s["name"] != t["name"]]
        self._changed()

    def export(self):
        t = self._selected_theme() or self.cur
        path, _ = QFileDialog.getSaveFileName(self, "Export theme", f"{t['name']}.theme.json", "Themes (*.theme.json)")
        if path:
            appearance.write_theme_file(t, path)
            self.app.toast(f"Exported {Path(path).name}.", "ok")

    def import_(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a theme", "", "Themes (*.theme.json *.json)")
        if not path:
            return
        try:
            t = appearance.read_theme_file(path)
        except (OSError, ValueError) as exc:
            dialogs.error("That theme can't be read", str(exc))
            return
        t["name"] = self._unique_name(t["name"])
        self.store["saved"].append(t)
        self.store["current"] = appearance.normalize(dict(t))
        self._changed()
        self.app.toast(f"Imported {t['name']}.", "ok")

    def reset_default(self):
        self.store["current"] = appearance.normalize(dict(appearance.DEFAULT_THEME))
        self._changed()

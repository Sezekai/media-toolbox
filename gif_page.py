"""The GIF maker screen: pick videos from several folders, set a timeframe, frame rate, width and name for any
of them, then convert. Ticked videos can be edited together in the selection bar."""
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

import collection as col
import dialogs
import fileops
import gif_maker
import icons
import jobs
import settings
import theme
from media_utils import find_videos, open_path, probe_video, show_in_explorer
from pages_common import ToolPage, plural
from tool_pages import SilentPage, file_actions
from widgets import (ElidedLabel, fit, add_folder, button, divider, field_label, label, line_edit, muted, remember,
                     repolish, results_panel, tool_row, toolbar)

MIN_CLIP = 0.1
FPS_MIN, FPS_MAX = 1, 60.0
WIDTH_MIN, WIDTH_MAX = 64, 3840
MIXED = "Mixed"


def fmt_time(seconds):
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def parse_time(text):
    """Seconds ("83.5") or m:ss.s ("1:23.5")."""
    text = text.strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return float(minutes) * 60 + float(seconds)
    return float(text)


def to_pixmap(pil_image):
    img = pil_image.convert("RGBA")
    qimg = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, 4 * img.width, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


class Timeline(QWidget):
    """The whole video as a bar, with the GIF's start and end handles on it."""
    changed = Signal(float, float)
    released = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.duration = self.start = self.end = 0.0
        self._drag = None
        self.setFixedHeight(46)
        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_range(self, duration, start, end):
        self.duration, self.start, self.end = duration, start, end
        self.update()

    def _x(self, t):
        span = max(1, self.width() - 12)
        return 6 + (t / self.duration) * span if self.duration else 6

    def _t(self, x):
        span = max(1, self.width() - 12)
        return min(max((x - 6) / span * self.duration, 0.0), self.duration)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        caption_h = theme.text_px("caption") + 6
        top, bottom = 6, h - caption_h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.RAISED2))
        p.drawRoundedRect(QRectF(6, top, w - 12, bottom - top), 4, 4)
        if self.duration:
            xs, xe = self._x(self.start), self._x(self.end)
            p.setBrush(QColor(theme.TINT_PILL))
            p.drawRect(QRectF(xs, top, max(1.0, xe - xs), bottom - top))
            p.setPen(QPen(QColor(theme.ACCENT), 3))
            for x in (xs, xe):
                p.drawLine(int(x), top - 3, int(x), bottom + 3)
        p.setPen(QColor(theme.FAINT))
        p.setFont(theme.font("caption"))
        cap = QRectF(6, bottom + 2, w - 12, caption_h)
        p.drawText(cap, Qt.AlignLeft | Qt.AlignVCenter, "0:00.0")
        p.drawText(cap, Qt.AlignRight | Qt.AlignVCenter, fmt_time(self.duration))
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


class Frame(QLabel):
    """One preview frame, fitted to its box."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(80, 60)
        self.source = None

    def sizeHint(self):
        return QSize(240, 135)

    def show_frame(self, pixmap):
        self.source = pixmap
        self.setText("")
        self._refresh()

    def show_message(self, text):
        self.source = None
        self.setPixmap(QPixmap())
        self.setText(text)
        self.setProperty("role", "empty")
        repolish(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if self.source is not None:
            self.setPixmap(fit(self.source, self.size() - QSize(4, 4), self.devicePixelRatioF()))


def _num_edit(width):
    e = line_edit(width=width)
    e.setAlignment(Qt.AlignRight)
    return e


class GifPage(ToolPage):
    title = "GIF maker"
    subtitle = "Turn videos into GIFs. Set a timeframe, frame rate, width or name for any video, or leave the defaults."
    key = "gif"
    icon = "gif"

    def build(self):
        saved = settings.load()
        self.current = None
        self._preview_id = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._request_previews)

        bar, rows = toolbar()
        top = tool_row()
        self.folders_row(top)
        self.go_btn = button("Convert", "primary", icons.icon("gif", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(self.convert)
        top.addWidget(self.go_btn)
        rows.addLayout(top)
        opts = tool_row()
        self.out_dir = line_edit(saved.get("gif_out", ""), "Empty = beside each video")
        add_folder(opts, "Save GIFs to", self.out_dir, "Save GIFs to", self._save)
        self.out_dir.editingFinished.connect(self._save)
        opts.addWidget(divider())
        self.size_mode = QComboBox()
        self.size_mode.addItem("Match each video", "match")
        self.size_mode.addItem("Same for all", "fixed")
        self.size_mode.setToolTip("Match each video: every GIF keeps its video's frame rate and width.\n"
                                  "Same for all: every GIF uses the FPS and width set here.\n"
                                  "Either way, any video can have its own values.")
        self.size_mode.setCurrentIndex(0 if saved.get("gif_size_mode", "match") == "match" else 1)
        self.size_mode.currentIndexChanged.connect(self._size_mode_changed)
        opts.addWidget(self.size_mode)
        self.fps = _num_edit(48)
        self.fps.setText(str(saved.get("gif_fps", "12")))
        self.width_px = _num_edit(60)
        self.width_px.setText(str(saved.get("gif_width", "480")))
        self.fps_label, self.width_label = muted("FPS"), muted("Width")
        for w in (self.fps_label, self.fps, self.width_label, self.width_px):
            opts.addWidget(w)
        for edit in (self.fps, self.width_px):
            edit.editingFinished.connect(self._defaults_changed)
        opts.addWidget(divider())
        opts.addWidget(muted("Quality"))
        self.quality = QComboBox()
        self.quality.addItems(list(gif_maker.QUALITY_PRESETS))
        self.quality.setCurrentText(saved.get("gif_quality", "Standard"))
        self.quality.setToolTip("Higher quality: better colours, bigger file, slower")
        self.quality.currentTextChanged.connect(lambda _t: self._save())
        opts.addWidget(self.quality)
        rows.addLayout(opts)
        self.body.addWidget(bar)
        self.panels.append(bar)

        # the selection bar: edit every ticked video at once (C5)
        self.selbar = QFrame()
        self.selbar.setObjectName("selbar")
        sb = QHBoxLayout(self.selbar)
        sb.setContentsMargins(theme.PAD, 4, 6, 4)
        sb.setSpacing(theme.GAP)
        self.sel_count = label("", "heading")
        sb.addWidget(self.sel_count)
        sb.addWidget(divider())
        sb.addWidget(muted("FPS"))
        self.sel_fps = _num_edit(66)
        sb.addWidget(self.sel_fps)
        sb.addWidget(muted("Width"))
        self.sel_width = _num_edit(66)
        sb.addWidget(self.sel_width)
        apply_sel = button("Set for ticked")
        apply_sel.setToolTip("Give every ticked video the FPS and width typed here (a box left at Mixed keeps "
                             "each video's own value)")
        apply_sel.clicked.connect(self._apply_selection)
        for e in (self.sel_fps, self.sel_width):
            e.returnPressed.connect(self._apply_selection)
        sb.addWidget(apply_sel)
        defaults = button("Use defaults", "ghost", tip="Forget the ticked videos' own FPS and width")
        defaults.clicked.connect(self._selection_defaults)
        sb.addWidget(defaults)
        clear_tf = button("Whole videos", "ghost", tip="Clear the ticked videos' timeframes")
        clear_tf.clicked.connect(self._selection_whole)
        sb.addWidget(clear_tf)
        sb.addStretch(1)
        untick = button("Untick all", "ghost")
        untick.clicked.connect(lambda: self.coll.tick_all(False))
        sb.addWidget(untick)
        self.selbar.hide()
        self.body.addWidget(self.selbar)

        columns = [col.name_column(),
                   col.Column("seconds", "Length", 62, text=lambda i: fmt_time(i["seconds"]) if i.get("seconds")
                              else "", sort=lambda i: i.get("seconds") or 0, align=Qt.AlignRight),
                   col.Column("clip", "Timeframe", 112, text=lambda i: (f"{fmt_time(i['clip'][0])} to "
                                                                      f"{fmt_time(i['clip'][1])}")
                              if i.get("clip") else "whole video",
                              sort=lambda i: (i["clip"][1] - i["clip"][0]) if i.get("clip") else 1e9),
                   col.Column("gif", "GIF", 120, text=self._output_text, sort=lambda i: self.settings_for(i)[1]),
                   col.status_column()]
        self.coll = col.Collection(
            "gif", columns, "video", ("video", "videos"), details=self._details,
            gallery_actions=file_actions(self),
            subline=lambda i: self._output_text(i),
            empty=("gif", "Add a folder to see its videos here. Click one to set its clip.", "Add folder…",
                   self.pick_root))
        self.coll.tree.remove_root.connect(self.remove_root)
        self.coll.ticks_changed.connect(self._ticks_changed)
        self.coll.selection_changed.connect(self._on_current)
        self.coll.view_changed.connect(lambda v: self.editor.setVisible(v != "gallery"))
        list_frame, lv = results_panel()
        lv.addWidget(self.coll)

        # the editor for the selected video
        self.editor, ev = results_panel()
        self.editor.setMinimumWidth(330)
        head = QHBoxLayout()
        head.setSpacing(theme.GAP)
        head.addWidget(label("Clip", "heading"))
        self.editor_hint = ElidedLabel("Click a video to set its clip.")
        head.addWidget(self.editor_hint, 1)
        ev.addLayout(head)
        self.timeline = Timeline()
        self.timeline.changed.connect(self._on_drag)
        self.timeline.released.connect(self._on_release)
        ev.addWidget(self.timeline)
        times = tool_row()
        self.start_edit = _num_edit(70)
        self.end_edit = _num_edit(70)
        for e in (self.start_edit, self.end_edit):
            e.returnPressed.connect(self._apply_entries)
            e.setToolTip("Seconds (12.5) or minutes:seconds (1:23.5). Enter applies.")
        whole_btn = button("Whole video", "ghost")
        whole_btn.clicked.connect(self._reset_range)
        times.addWidget(muted("Start"))
        times.addWidget(self.start_edit)
        times.addWidget(muted("End"))
        times.addWidget(self.end_edit)
        times.addWidget(whole_btn)
        times.addStretch(1)
        self.length_label = label("", "value")
        times.addWidget(self.length_label)
        ev.addLayout(times)
        own = tool_row()
        self.own_fps = _num_edit(56)
        self.own_width = _num_edit(64)
        for e in (self.own_fps, self.own_width):
            e.returnPressed.connect(self._apply_own)
            e.editingFinished.connect(self._apply_own)
        own.addWidget(muted("FPS"))
        own.addWidget(self.own_fps)
        own.addWidget(muted("Width"))
        own.addWidget(self.own_width)
        self.use_defaults = button("Use defaults", "ghost", tip="Forget this video's own FPS and width")
        self.use_defaults.clicked.connect(self._clear_own)
        own.addWidget(self.use_defaults)
        self.own_note = ElidedLabel("", "caption")
        own.addWidget(self.own_note, 1)
        ev.addLayout(own)
        name_row = tool_row()
        name_row.addWidget(muted("Name"))
        self.name_edit = line_edit()
        self.name_edit.setToolTip("The GIF's file name. A taken name gets “(2)”.")
        self.name_edit.editingFinished.connect(self._apply_name)
        name_row.addWidget(self.name_edit, 1)
        ev.addLayout(name_row)
        frames = QHBoxLayout()
        frames.setSpacing(theme.GAP)
        self.start_view, self.end_view = Frame(), Frame()
        frames.addWidget(self._frame_box("Starts at", self.start_view), 1)
        frames.addWidget(self._frame_box("Ends at", self.end_view), 1)
        ev.addLayout(frames, 1)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.GAP)
        split.addWidget(list_frame)
        split.addWidget(self.editor)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        remember("gif_split", split)
        self.body.addWidget(split, 1)
        self.panels += [self.coll.tree_panel]
        self.coll.set_roots(self.roots)
        self._size_mode_changed()
        self._clear_editor()
        self._loaded = False
        self.editor.setVisible(self.coll.view() != "gallery")

    _open = SilentPage._open

    def _frame_box(self, caption, view):
        box = QFrame()
        box.setObjectName("preview")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)
        layout.addWidget(label(caption, "caption"))
        layout.addWidget(view, 1)
        return box

    def _save(self):
        settings.save({"gif_out": self.out_dir.text().strip(), "gif_quality": self.quality.currentText(),
                       "gif_fps": self.fps.text().strip(), "gif_width": self.width_px.text().strip(),
                       "gif_size_mode": self.size_mode.currentData()})

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
        old = {i["path"]: i for i in self.coll.items()}
        self.app.start(jobs.Job("Listing videos", self._list_job, roots, recursive, old, short="Listing",
                                done=self._listed))

    def _list_job(self, roots, recursive, old, log, progress):
        items = []
        for n, root in enumerate(roots):
            progress(n, len(roots), f"Looking in {Path(root).name}")
            for p in find_videos(root, recursive):
                prev = old.get(str(p))
                items.append(prev if prev else col.make_item(p, root, seconds=None, clip=None, info={}, own=None,
                                                             gif_name=""))
        return {"summary": f"{plural(len(items), 'video')} found", "items": items}

    def _listed(self, job):
        if not isinstance(job.result, dict):
            return
        items = job.result["items"]
        self.coll.set_items(items)
        self.coll.set_empty("No videos in these folders." if self.roots else
                            "Add a folder to see its videos here. Click one to set its clip.", "Add folder…")
        self.refresh_buttons()
        todo = [i["path"] for i in items if not i.get("info")]
        if todo:
            threading.Thread(target=self._read_info, args=(todo,), daemon=True).start()

    def _read_info(self, todo):
        """Read every video's length, frame rate and size in the background."""
        for path in todo:
            try:
                info = probe_video(path)
            except Exception:
                info = {}
            self.app.on_main(lambda p=path, i=info: self._set_info(p, i))

    def _set_info(self, path, info):
        item = self.coll.update(path, info=info, seconds=info.get("duration"))
        if item is not None and self.current is item:
            self._show_editor(item)

    # ----- frame rate and width -----
    def _defaults(self):
        try:
            fps, width = float(self.fps.text()), int(self.width_px.text())
        except ValueError:
            return None
        if not (FPS_MIN <= fps <= FPS_MAX) or not (WIDTH_MIN <= width <= WIDTH_MAX):
            return None
        return fps, width

    def settings_for(self, item):
        if item.get("own"):
            return tuple(item["own"])
        fixed = self._defaults() or (12.0, 480)
        if self.size_mode.currentData() == "match":
            info = item.get("info") or {}
            fps, width = info.get("fps"), info.get("width")
            fps = round(min(max(fps, FPS_MIN), FPS_MAX), 2) if fps else fixed[0]
            width = min(max(width, WIDTH_MIN), WIDTH_MAX) if width else fixed[1]
            return fps, width
        return fixed

    def _output_text(self, item):
        fps, width = self.settings_for(item)
        return f"{fps:g} fps · {width} px"

    def _defaults_changed(self):
        if self._defaults() is None:
            self.app.toast(f"FPS must be {FPS_MIN} to {FPS_MAX:g}, and width {WIDTH_MIN} to {WIDTH_MAX} px.", "warn")
            return
        self._save()
        self._refresh_all()

    def _size_mode_changed(self):
        fixed = self.size_mode.currentData() == "fixed"
        for w in (self.fps_label, self.fps, self.width_label, self.width_px):
            w.setEnabled(fixed)
        self._save()
        self._refresh_all()

    def _refresh_all(self):
        for item in self.coll.items():
            self.coll.model.changed(item)
        if self.current:
            self._show_own(self.current)
        self._ticks_changed()

    def _details(self, item):
        info = item.get("info") or {}
        rows = [("Length", fmt_time(item["seconds"]) if item.get("seconds") else "reading…"),
                ("Video", f"{info.get('width')}×{info.get('height')} · {info.get('fps') or 0:.3g} fps"
                 if info.get("width") else "reading…"),
                ("Timeframe", self.coll.model.columns[2].text(item)),
                ("GIF", self._output_text(item) + (" (own)" if item.get("own") else "")),
                ("Size", fileops.human_size(item["size"]))]
        if item.get("detail"):
            rows.append(("Result", item["detail"]))
        return rows

    # ----- the editor -----
    def _on_current(self, item):
        if item is None or item is self.current:
            return
        self.current = item
        self._show_editor(item)

    def _show_editor(self, item):
        self.editor_hint.setText(item["name"])
        self._show_own(item)
        self.name_edit.setPlaceholderText(Path(item["path"]).stem + ".gif")
        self.name_edit.setText(item.get("gif_name", ""))
        duration = item.get("seconds")
        if not duration:
            self.timeline.set_range(0, 0, 0)
            self.start_view.show_message("Reading the video…")
            self.end_view.show_message("")
            return
        start, end = item.get("clip") or (0.0, duration)
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._request_previews()

    def _clear_editor(self):
        self.current = None
        self.timeline.set_range(0.0, 0.0, 0.0)
        for e in (self.start_edit, self.end_edit, self.own_fps, self.own_width, self.name_edit):
            e.setText("")
        self.length_label.setText("")
        self.own_note.setText("")
        self.use_defaults.hide()
        self.editor_hint.setText("Click a video to set its clip.")
        self.start_view.show_message("No video selected")
        self.end_view.show_message("No video selected")

    def _update_labels(self, start, end):
        self.start_edit.setText(fmt_time(start))
        self.end_edit.setText(fmt_time(end))
        self.length_label.setText(f"{end - start:.1f} s")

    def _store(self, start, end):
        item = self.current
        if item is None or not item.get("seconds"):
            return
        duration = item["seconds"]
        clip = None if start <= 0.05 and end >= duration - 0.05 else (start, end)
        self.coll.update(item["path"], clip=clip)

    def _on_drag(self, start, end):
        self._update_labels(start, end)
        self._store(start, end)
        self._preview_timer.start()

    def _on_release(self, start, end):
        self._store(start, end)
        self._request_previews()

    def _apply_entries(self):
        item = self.current
        if not item or not item.get("seconds"):
            return
        duration = item["seconds"]
        try:
            start, end = parse_time(self.start_edit.text()), parse_time(self.end_edit.text())
        except ValueError:
            self.app.toast("Type times like 12.5 or 1:23.5.", "warn")
            return
        start, end = max(0.0, min(start, duration)), max(0.0, min(end, duration))
        if end - start < MIN_CLIP:
            self.app.toast(f"The end must be at least {MIN_CLIP} s after the start.", "warn")
            return
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._store(start, end)
        self._request_previews()

    def _reset_range(self):
        if self.current:
            self.coll.update(self.current["path"], clip=None)
            self._show_editor(self.current)

    def _show_own(self, item):
        fps, width = self.settings_for(item)
        self.own_fps.setText(f"{fps:g}")
        self.own_width.setText(str(width))
        own = bool(item.get("own"))
        for e in (self.own_fps, self.own_width):
            e.setStyleSheet(f"color: {theme.ACCENT};" if own else "")  # own values show in the accent
        self.use_defaults.setVisible(own)
        info = item.get("info") or {}
        if own:
            note = "This video's own values."
        elif self.size_mode.currentData() == "match" and info.get("fps"):
            note = f"From the video ({info['fps']:.3g} fps, {info.get('width')}×{info.get('height')})."
        else:
            note = "The defaults in the bar above."
        self.own_note.setText(note)

    def _apply_own(self):
        item = self.current
        if item is None:
            return
        try:
            fps, width = float(self.own_fps.text()), int(self.own_width.text())
        except ValueError:
            self._show_own(item)
            return
        if not (FPS_MIN <= fps <= FPS_MAX) or not (WIDTH_MIN <= width <= WIDTH_MAX):
            self.app.toast(f"FPS must be {FPS_MIN} to {FPS_MAX:g}, and width {WIDTH_MIN} to {WIDTH_MAX} px.", "warn")
            self._show_own(item)
            return
        if (fps, width) == self.settings_for(item):
            return
        self.coll.update(item["path"], own=(fps, width))
        self._show_own(item)
        self._ticks_changed()

    def _clear_own(self):
        if self.current:
            self.coll.update(self.current["path"], own=None)
            self._show_own(self.current)
            self._ticks_changed()

    def _apply_name(self):
        if self.current is None:
            return
        name = self.name_edit.text().strip()
        cleaned = gif_maker.clean_name(name) if name else ""
        if name and cleaned != name and cleaned[:-4] != name:
            self.name_edit.setText(cleaned)
        self.coll.update(self.current["path"], gif_name=cleaned)

    # ----- previews -----
    def _request_previews(self):
        item = self.current
        if not item:
            return
        path = item["path"]
        start, end = self.timeline.start, self.timeline.end
        self._preview_id += 1
        token = self._preview_id

        def worker():
            first = gif_maker.extract_frame(path, start)
            last = gif_maker.extract_frame(path, max(end - 0.05, start))
            self.app.on_main(lambda: self._show_previews(token, first, last))

        threading.Thread(target=worker, daemon=True).start()

    def _show_previews(self, token, first, last):
        if token != self._preview_id:
            return
        for view, img in ((self.start_view, first), (self.end_view, last)):
            view.show_frame(to_pixmap(img)) if img is not None else view.show_message("This frame can't be read")

    # ----- the selection bar -----
    def _ticks_changed(self):
        ticked = self.coll.ticked()
        self.selbar.setVisible(len(ticked) >= 2)
        if len(ticked) >= 2:
            self.sel_count.setText(f"{len(ticked)} ticked")
            values = [self.settings_for(i) for i in ticked]
            owns = [bool(i.get("own")) for i in ticked]
            for n, edit in ((0, self.sel_fps), (1, self.sel_width)):
                vals = {v[n] for v in values}
                edit.setText("" if len(vals) > 1 else (f"{vals.pop():g}" if n == 0 else str(vals.pop())))
                edit.setPlaceholderText(MIXED)
                edit.setStyleSheet(f"color: {theme.ACCENT};" if all(owns) else "")
        self.refresh_buttons()

    def _apply_selection(self):
        ticked = self.coll.ticked()
        fps_t, width_t = self.sel_fps.text().strip(), self.sel_width.text().strip()
        try:
            fps = float(fps_t) if fps_t else None
            width = int(width_t) if width_t else None
        except ValueError:
            self.app.toast("Type numbers for FPS and width.", "warn")
            return
        if (fps is not None and not FPS_MIN <= fps <= FPS_MAX) or (width is not None
                                                                   and not WIDTH_MIN <= width <= WIDTH_MAX):
            self.app.toast(f"FPS must be {FPS_MIN} to {FPS_MAX:g}, and width {WIDTH_MIN} to {WIDTH_MAX} px.", "warn")
            return
        for item in ticked:
            cur = self.settings_for(item)
            self.coll.update(item["path"], own=(fps if fps is not None else cur[0],
                                                width if width is not None else cur[1]))
        self.app.toast(f"Set for {plural(len(ticked), 'video')}.", "ok", 4)
        self._refresh_all()

    def _selection_defaults(self):
        for item in self.coll.ticked():
            self.coll.update(item["path"], own=None)
        self._refresh_all()

    def _selection_whole(self):
        for item in self.coll.ticked():
            self.coll.update(item["path"], clip=None)
        if self.current:
            self._show_editor(self.current)

    # ----- converting -----
    def refresh_buttons(self):
        ticked, total = len(self.coll.ticked()), len(self.coll.items())
        if ticked:
            self.set_main(self.go_btn, f"Convert {plural(ticked, 'ticked video')}", plural(ticked, "video"))
        else:
            self.set_main(self.go_btn, f"Convert all {plural(total, 'video')}" if total else "Convert",
                          plural(total, "video"))

    def convert(self):
        items = [i for i in (self.coll.ticked() or self.coll.items()) if Path(i["path"]).exists()]
        if not items:
            dialogs.info("Nothing to convert", "Add a folder with videos first.", icon_name="gif")
            return
        if self.size_mode.currentData() == "fixed" and self._defaults() is None:
            dialogs.error("Check the FPS and width", f"FPS must be {FPS_MIN} to {FPS_MAX:g}, and width {WIDTH_MIN} "
                          f"to {WIDTH_MAX} pixels.")
            return
        out_dir = self.out_dir.text().strip() or None
        self._save()
        todo = []
        for item in items:
            fps, width = self.settings_for(item)
            start, end = item.get("clip") or (0.0, None)
            todo.append((item["path"], start, end, fps, width, item.get("gif_name") or None))
            self.coll.update(item["path"], status="Queued", detail="")
        self.app.start(jobs.Job(f"Making {plural(len(todo), 'GIF')}", self._convert_job, todo,
                                self.quality.currentText(), out_dir, short="Making GIFs",
                                done=lambda _j: self.refresh_buttons()))

    def _convert_job(self, todo, quality, out_dir, log, progress):
        def state(path, status, detail):
            self.app.on_main(lambda: self.coll.update(path, status=status, detail=detail))
        try:
            made, failed = gif_maker.convert_batch(todo, quality, out_dir, log, progress, state)
        finally:
            paths = [t[0] for t in todo]
            self.app.on_main(lambda: [self.coll.update(p, status="") for p in paths
                                      if (self.coll.find(p) or {}).get("status") in ("Queued", "Working")])
        first = out_dir or str(Path(todo[0][0]).parent)
        return {"summary": f"{made} made, {failed} failed", "next": ("Open the folder", lambda: open_path(first))}

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

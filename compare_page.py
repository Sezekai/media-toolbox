"""Compare: watch copies of a video side by side, in step, and keep the best.

Pick a folder: every folder in it (and the folder itself) with two or more videos becomes a comparison. Each
comparison plays all its videos at once, lined up so the same moment shows at the same time even when the
copies start or end at different points. One control bar runs them all. Over each video are its details,
with the best picture and the best sound marked; the sound plays from the best-sounding copy and you can
listen to any other. Wheel to zoom into a video, drag to move around it, double-click to fit it again: each
keeps its own zoom while playing.

Tick what to keep. Apply combines picture and sound first when asked (the best picture with another copy's
sound, lined up, the picture never re-encoded), then sends the others to the Recycle Bin. A file the Recycle
Bin won't take is reported and left alone; nothing is ever deleted for good."""
import math
import time
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsScene, QGraphicsView,
                               QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

import compare_engine as ce
import dialogs
import fileops
import icons
import jobs
import preview
import settings
import theme
from app_pages import Box, splitter
from pages_common import plural
from widgets import Page, button, label, line_edit, repolish, tag, tool_row, toolbar

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

ROLE = Qt.UserRole
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]


def _state_file():
    import paths
    return paths.ensure(paths.place("data")) / "compare_state.json"


# ----- one video: zoom with the wheel, drag to move, click to play or pause, double-click to fit -----
class ZoomView(QGraphicsView):
    """Wheel zooms and dragging moves every video together (the page passes it on); with Ctrl held, only this
    one. Positions are passed as fractions of the view, so videos of different sizes move alike."""
    clicked = Signal()
    zoom_all = Signal(float, float, float)   # factor, x and y of the pointer as fractions of the view
    pan_all = Signal(float, float)           # how far to move, as fractions of the view
    fit_all = Signal()

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(theme.STAGE)))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsVideoItem() if AVAILABLE else None
        if self.item is not None:
            self.item.setAspectRatioMode(Qt.KeepAspectRatio)
            self.scene().addItem(self.item)
        self.scale_ = 1.0
        self._press = None
        self._last = None
        self.note = QLabel(self.viewport())
        self.note.setObjectName("comparenote")
        self.note.hide()
        self.setToolTip("Wheel: zoom all · drag: move all · with Ctrl: just this one · click: play or pause · "
                        "double-click: fit")
        self.setMinimumSize(80, 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_item()
        self._place_note()

    def _fit_item(self):
        w, h = max(1, self.viewport().width()), max(1, self.viewport().height())
        if self.item is not None:
            self.item.setSize(QSizeF(w, h))
        self.scene().setSceneRect(QRectF(0, 0, w, h))

    def zoom_by(self, factor, at=None):
        """Zoom, keeping the picture under `at` (a point in the view; the middle when None) where it is."""
        new = max(1.0, min(16.0, self.scale_ * factor))
        if abs(new - self.scale_) < 1e-6:
            return
        vp = self.viewport()
        at = QPointF(vp.width() / 2, vp.height() / 2) if at is None else QPointF(at)
        before = self.mapToScene(at.toPoint())
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(new / self.scale_, new / self.scale_)
        self.scale_ = new
        after = self.mapFromScene(before)
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(after.x() - at.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(after.y() - at.y()))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        if new == 1.0:
            self.fit()

    def zoom_frac(self, factor, fx, fy):
        vp = self.viewport()
        self.zoom_by(factor, QPointF(fx * vp.width(), fy * vp.height()))

    def pan_frac(self, fdx, fdy):
        vp = self.viewport()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(round(fdx * vp.width())))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(round(fdy * vp.height())))

    def fit(self):
        self.resetTransform()
        self.scale_ = 1.0
        self.centerOn(self.sceneRect().center())

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            factor = 1.25 ** steps
            if event.modifiers() & Qt.ControlModifier:
                self.zoom_by(factor, event.position())          # Ctrl: just this video
            else:
                vp = self.viewport()
                self.zoom_all.emit(factor, event.position().x() / max(1, vp.width()),
                                   event.position().y() / max(1, vp.height()))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = self._last = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._last is not None:
            d = event.position() - self._last
            self._last = event.position()
            vp = self.viewport()
            fdx, fdy = d.x() / max(1, vp.width()), d.y() / max(1, vp.height())
            if event.modifiers() & Qt.ControlModifier:
                self.pan_frac(fdx, fdy)                           # Ctrl: just this video
            else:
                self.pan_all.emit(fdx, fdy)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press is not None:
            moved = (event.position() - self._press).manhattanLength()
            self._press = self._last = None
            self.viewport().unsetCursor()
            if moved < 5:
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                self.fit()
            else:
                self.fit_all.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def set_note(self, text):
        if text:
            self.note.setText(text)
            self.note.adjustSize()
            self._place_note()
            self.note.show()
        else:
            self.note.hide()

    def _place_note(self):
        self.note.move((self.viewport().width() - self.note.width()) // 2,
                       (self.viewport().height() - self.note.height()) // 2)


# ----- one tile: details over the video -----
class Tile(QFrame):
    keep_changed = Signal()
    listen_requested = Signal(int)
    nudged = Signal(int, float)

    def __init__(self, index, info, best_video, best_audio):
        super().__init__()
        self.index, self.info = index, info
        self.setObjectName("ctile")
        self.setProperty("best", "true" if best_video else "false")
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.head = QWidget()
        hv = QVBoxLayout(self.head)
        hv.setContentsMargins(2, 0, 2, 0)
        hv.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        num = label(str(index + 1), "value")
        num.setObjectName("tilenum")
        top.addWidget(num)
        name = label(info["name"], "heading")
        name.setToolTip(info["path"])
        name.setMinimumWidth(40)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(name, 1)
        if best_video:
            top.addWidget(tag("Best picture", "acc"))
        if best_audio:
            top.addWidget(tag("Best sound", "plain"))
        hv.addLayout(top)
        self.details = label("\n".join(ce.describe(info)), "caption")
        self.details.setWordWrap(True)
        hv.addWidget(self.details)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.keep = button("Keep", "secondary", icons.icon("check", theme.TEXT, 14),
                           tip=f"Keep or recycle this copy (Ctrl+{index + 1})")
        self.keep.setCheckable(True)
        self.keep.toggled.connect(self._keep_toggled)
        self.listen = button("", "ghost", icons.icon("sound", theme.SEC, 16),
                             tip=f"Listen to this copy's sound ({index + 1})")
        self.listen.setCheckable(True)
        self.listen.clicked.connect(lambda: self.listen_requested.emit(self.index))
        self.listen.setEnabled(bool(info.get("audio")))
        back = button("−", "ghost", tip="Show this one a frame earlier")
        back.clicked.connect(lambda: self.nudged.emit(self.index, -1))
        fwd = button("+", "ghost", tip="Show this one a frame later")
        fwd.clicked.connect(lambda: self.nudged.emit(self.index, 1))
        self.offset = label("", "caption")
        self.offset.setToolTip("Where this copy starts on the shared timeline. − and + move it a frame, if it "
                               "looks a little out of step.")
        for w in (self.keep, self.listen):
            row.addWidget(w)
        row.addStretch(1)
        for w in (self.offset, back, fwd):
            row.addWidget(w)
        back.setFixedWidth(38)
        fwd.setFixedWidth(38)
        hv.addLayout(row)
        v.addWidget(self.head)
        self.view = ZoomView()
        v.addWidget(self.view, 1)

    def _keep_toggled(self, on):
        self.keep.setText("Keep" if on else "Recycle")
        self.keep.setIcon(icons.icon("check" if on else "trash", theme.TEXT if on else theme.DANGER, 14))
        self.setProperty("drop", "false" if on else "true")
        repolish(self)
        self.keep_changed.emit()

    def set_keep(self, on):
        if self.keep.isChecked() == on:
            self._keep_toggled(on)
        self.keep.setChecked(on)

    def set_offset(self, seconds, sure):
        text = f"starts at {fileops.clock(seconds)}" if seconds >= 0.05 else "starts first"
        if 0 < sure < 0.35:
            text += " · line-up unsure"
        self.offset.setText(text)


class TileGrid(QWidget):
    """Tiles in the arrangement that makes the videos biggest: side by side, stacked or a grid."""

    def __init__(self):
        super().__init__()
        self.tiles = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(theme.GAP - 2)
        self._cols = 0

    def set_tiles(self, tiles):
        for t in self.tiles:
            self.grid.removeWidget(t)
            t.hide()
            t.deleteLater()
        self.tiles = tiles
        self._cols = 0
        self.arrange()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def arrange(self, force=False):
        n = len(self.tiles)
        if not n:
            return
        W, H = max(1, self.width()), max(1, self.height())
        ratios = []
        for t in self.tiles:
            v = t.info.get("video") or {}
            ratios.append((v.get("width") or 16) / max(1, v.get("height") or 9))
        ratio = sum(ratios) / len(ratios)
        head = self.tiles[0].head.sizeHint().height() if self.tiles[0].head.isVisible() else 0
        best_cols, best_area = 1, -1
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            cw, ch = W / cols, H / rows - head - 16
            if ch <= 0:
                continue
            vw = min(cw, ch * ratio)
            area = vw * (vw / ratio)
            if area > best_area:
                best_cols, best_area = cols, area
        if best_cols == self._cols and not force:
            return
        self._cols = best_cols
        for t in self.tiles:
            self.grid.removeWidget(t)
        for k, t in enumerate(self.tiles):
            self.grid.addWidget(t, k // best_cols, k % best_cols)
            t.show()
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < best_cols else 0)
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 1 if r < math.ceil(n / best_cols) else 0)


# ----- the screen -----
class ComparePage(Page):
    title = "Compare videos"
    subtitle = ("Watch copies side by side, in step, then keep the best. Every folder with two or more videos "
                "is a comparison.")
    key = "compare"
    icon = "compare"
    own_keys = ("Compare videos", [
        ("Space", "Play or pause every video"), ("Click a video", "Play or pause"),
        ("← →", "Back or forward 3 seconds"), ("Shift+← →", "Back or forward 5 seconds"),
        (", / .", "A frame back or forward (9 / 0 too)"), ("[ / ]", "Slower or faster"),
        ("1–8", "Listen to that copy's sound"), ("Ctrl+1–8", "Keep or recycle that copy"),
        ("M", "Mute or unmute"), ("↑ ↓", "Volume"),
        ("Wheel", "Zoom every video, at the pointer"), ("Ctrl+wheel", "Zoom just the video under the pointer"),
        ("Drag", "Move around every zoomed video"), ("Ctrl+drag", "Move just that video"),
        ("Double-click", "Fit every video (Ctrl: just that one)"), ("+ / −", "Zoom every video"),
        ("Z", "Fit every video"),
        ("C", "Combine picture and sound on or off"), ("Enter", "Apply and go to the next comparison"),
        ("PgUp PgDn", "Previous or next comparison"), ("Home / End", "First or last comparison"),
        ("H, then F", "Hide everything but the videos, then full screen"), ("Ctrl+A", "Keep all, or none")])

    def build(self):
        self.groups = []          # [{"folder", "videos"}]
        self.index = -1
        self.data = None          # the prepared comparison: infos, offsets, best_video, best_audio
        self.players = []
        self.audio = None
        self.listen_to = None
        self.playing = False
        self.T = 0.0              # position on the shared timeline, in seconds
        self.base_T = 0.0
        self.clock = QElapsedTimer()
        self.speed = 1.0
        self.muted = False
        self.loop = True
        self.preparing = None
        self.state = fileops.read_json(_state_file(), {})
        preview.on_release(self.release_files)

        # toolbar
        bar, rows = toolbar()
        row = tool_row()
        row.addWidget(label("Folder", "muted"))
        self.folder = line_edit(settings.load().get("compare_root", ""), "Choose a folder of comparisons")
        self.folder.editingFinished.connect(self._folder_typed)
        row.addWidget(self.folder, 1)
        browse = button("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        self.find_btn = button("Find comparisons", "primary", icons.icon("search", theme.ON_ACCENT, 16))
        self.find_btn.clicked.connect(self.find)
        row.addWidget(self.find_btn)
        rows.addLayout(row)
        row2 = tool_row()
        s = settings.load()
        self.move_on = QCheckBox("Move kept videos to")
        self.move_on.setChecked(bool(s.get("compare_move_on")))
        self.move_on.setToolTip("After applying, the videos you kept move here and the comparison's folder, once "
                                "empty, goes to the Recycle Bin. Moves can be undone (Ctrl+Z).")
        self.move_on.toggled.connect(self._move_changed)
        row2.addWidget(self.move_on)
        self.move_to = line_edit(s.get("compare_move_to", ""), "Choose where kept videos go")
        self.move_to.editingFinished.connect(self._move_changed)
        row2.addWidget(self.move_to, 1)
        move_browse = button("Browse")
        move_browse.clicked.connect(self._browse_move)
        row2.addWidget(move_browse)
        self.move_note = label("then the emptied folders go to the Recycle Bin", "caption")
        row2.addWidget(self.move_note)
        rows.addLayout(row2)
        self.body.addWidget(bar)
        self.panels.append(bar)

        # left: the comparisons
        self.list_box = Box("Comparisons", min_w=210)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.currentRowChanged.connect(self._picked)
        self.list_box.v.addWidget(self.list, 1)
        self.list_note = label("", "caption", wrap=True)
        self.list_box.v.addWidget(self.list_note)
        self.panels.append(self.list_box)

        # middle: tiles, decision, controls
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(theme.GAP - 2)
        self.empty = label("Choose a folder and press Find comparisons. Each folder with two or more videos "
                           "becomes one comparison.", "empty", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        mv.addWidget(self.empty, 1)
        self.grid = TileGrid()
        self.grid.hide()
        mv.addWidget(self.grid, 1)

        # decision bar
        self.decide = QFrame()
        self.decide.setObjectName("panel")
        dh = QHBoxLayout(self.decide)
        dh.setContentsMargins(theme.PAD, 6, theme.PAD, 6)
        dh.setSpacing(theme.GAP)
        self.decision = label("", "value")
        dh.addWidget(self.decision)
        self.combine = QCheckBox("Combine")
        self.combine.setToolTip("Put one copy's sound with another copy's picture (lined up). The picture is "
                                "copied as it is, never re-encoded. Done before anything is recycled.")
        self.combine.toggled.connect(self._decision_changed)
        dh.addWidget(self.combine)
        dh.addWidget(label("picture from", "muted"))
        self.pic_from = QComboBox()
        self.pic_from.setMinimumWidth(170)
        self.pic_from.currentIndexChanged.connect(self._decision_changed)
        dh.addWidget(self.pic_from)
        dh.addWidget(label("with sound from", "muted"))
        self.snd_from = QComboBox()
        self.snd_from.setMinimumWidth(170)
        self.snd_from.currentIndexChanged.connect(self._decision_changed)
        dh.addWidget(self.snd_from)
        dh.addStretch(1)
        skip = button("Skip", "ghost", tip="Leave this comparison for now (PgDn)")
        skip.clicked.connect(lambda: self.step(1))
        dh.addWidget(skip)
        self.apply_btn = button("Apply and next", "primary", icons.icon("check", theme.ON_ACCENT, 16),
                                tip="Combine (if ticked), recycle the copies not kept, then go to the next (Enter)")
        self.apply_btn.clicked.connect(self.apply)
        dh.addWidget(self.apply_btn)
        self.decide.hide()
        mv.addWidget(self.decide)  # shown only while a comparison is open (and panels aren't hidden)

        # one control bar for every video
        self.controls = QFrame()
        self.controls.setObjectName("panel")
        ch = QHBoxLayout(self.controls)
        ch.setContentsMargins(theme.PAD, 6, theme.PAD, 6)
        ch.setSpacing(theme.GAP - 2)
        self.play_btn = button("", "ghost", icons.icon("play", theme.TEXT, 18), tip="Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle)
        ch.addWidget(self.play_btn)
        self.pos = QSlider(Qt.Horizontal)
        self.pos.setRange(0, 1000)
        self.pos.sliderMoved.connect(lambda v: self.seek(v / 1000))
        self.pos.sliderPressed.connect(lambda: self.seek(self.pos.value() / 1000))
        ch.addWidget(self.pos, 1)
        self.time = label("0:00 / 0:00", "caption")
        ch.addWidget(self.time)
        self.speed_btn = button("1×", "ghost", tip="Speed ([ and ])")
        self.speed_btn.clicked.connect(lambda: self.set_speed(1))
        ch.addWidget(self.speed_btn)
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setChecked(True)
        self.loop_box.toggled.connect(lambda on: setattr(self, "loop", on))
        ch.addWidget(self.loop_box)
        self.mute_btn = button("", "ghost", icons.icon("sound", theme.TEXT, 16), tip="Mute (M)")
        self.mute_btn.clicked.connect(self.toggle_mute)
        ch.addWidget(self.mute_btn)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(90)
        self.vol.setValue(int(float(settings.load().get("volume", 0.6)) * 100))
        self.vol.setToolTip("Volume (↑ ↓)")
        self.vol.valueChanged.connect(self._volume)
        ch.addWidget(self.vol)
        self.controls.hide()
        mv.addWidget(self.controls)

        self.cols = splitter("compare_cols", Qt.Horizontal, [self.list_box, mid], [250, 1100])
        self.body.addWidget(self.cols, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        if self.folder.text().strip():
            QTimer.singleShot(0, lambda: self.find(quiet=True))

    # ----- folders -----
    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "A folder of comparisons", self.folder.text().strip())
        if chosen:
            self.folder.setText(str(Path(chosen)))
            self._folder_typed()
            self.find()

    def _browse_move(self):
        chosen = QFileDialog.getExistingDirectory(self, "Move kept videos to", self.move_to.text().strip())
        if chosen:
            self.move_to.setText(str(Path(chosen)))
            self.move_on.setChecked(True)
            self._move_changed()

    def _move_changed(self, *_a):
        settings.save({"compare_move_on": self.move_on.isChecked(),
                       "compare_move_to": self.move_to.text().strip()})
        self.move_to.setEnabled(True)
        self._decision_changed()

    def _move_target(self):
        """The folder kept videos move to, or None when moving is off."""
        if not self.move_on.isChecked():
            return None
        target = self.move_to.text().strip()
        return target or None

    def _folder_typed(self):
        settings.save({"compare_root": self.folder.text().strip()})

    def find(self, quiet=False, select=None):
        root = self.folder.text().strip()
        if not root or not Path(root).is_dir():
            if not quiet:
                dialogs.info("Choose a folder", "Choose the folder that holds your comparison folders.",
                             icon_name="folder")
            return
        self._folder_typed()
        self.groups = ce.find_comparisons(root)
        self.list.blockSignals(True)
        self.list.clear()
        for g in self.groups:
            rel = Path(g["folder"]).relative_to(root) if Path(g["folder"]) != Path(root) else Path(".")
            it = QListWidgetItem(f"{'.' if str(rel) == '.' else rel}  ·  {len(g['videos'])}")
            it.setToolTip(g["folder"])
            done = self.state.get(g["folder"], {}).get("done")
            it.setIcon(icons.icon("check" if done else "compare", theme.OK if done else theme.SEC, 14))
            self.list.addItem(it)
        self.list.blockSignals(False)
        todo = sum(1 for g in self.groups if not self.state.get(g["folder"], {}).get("done"))
        self.list_note.setText(f"{plural(len(self.groups), 'comparison')}, {todo} to do." if self.groups else
                               "No folders with two or more videos here.")
        if self.groups:
            first = next((k for k, g in enumerate(self.groups) if g["folder"] == select), None)
            if first is None:
                first = next((k for k, g in enumerate(self.groups)
                              if not self.state.get(g["folder"], {}).get("done")), 0)
            self.index = -1
            self.list.setCurrentRow(first)
            if self.list.currentRow() == first and self.index != first:
                self.open(first)
        else:
            self._clear()

    def _picked(self, row):
        if 0 <= row < len(self.groups) and row != self.index:
            self.open(row)

    # ----- opening a comparison -----
    def open(self, row):
        self.pause()
        self.release_files()
        self.index = row
        group = self.groups[row]
        videos = [v for v in group["videos"] if Path(v).exists()]
        if len(videos) < 2:
            self._clear(f"Fewer than two videos are left in {Path(group['folder']).name}.")
            return
        self._clear("Lining up the videos…")
        self.preparing = group["folder"]
        self.app.start(jobs.Job(f"Lining up {plural(len(videos), 'video')}", ce.prepare, videos, short="Lining up",
                                done=lambda j, f=group["folder"]: self._prepared(j, f),
                                failed=lambda j: self._clear(f"Couldn't read these videos: {j.error}")))

    def _prepared(self, job, folder):
        if job.finished != "done" or not (0 <= self.index < len(self.groups)) \
                or self.groups[self.index]["folder"] != folder:
            return
        self.data = job.result
        infos = self.data["infos"]
        bv, ba = self.data["best_video"], self.data["best_audio"]
        saved = self.state.get(folder, {})
        nudges = saved.get("nudge", {})
        self.offsets = [o + float(nudges.get(i["path"], 0)) for o, i in zip(self.data["offsets"], infos)]
        tiles = []
        for k, info in enumerate(infos):
            t = Tile(k, info, k == bv, k == ba)
            t.set_keep(k == bv)
            t.keep_changed.connect(self._decision_changed)
            t.listen_requested.connect(self.listen)
            t.nudged.connect(self.nudge)
            t.view.clicked.connect(self.toggle)
            t.view.zoom_all.connect(lambda f, x, y: [tt.view.zoom_frac(f, x, y) for tt in self.grid.tiles])
            t.view.pan_all.connect(lambda dx, dy: [tt.view.pan_frac(dx, dy) for tt in self.grid.tiles])
            t.view.fit_all.connect(self.fit)
            t.set_offset(self.offsets[k], self.data["sure"][k])
            t.head.setVisible(not self.app.panels_hidden)
            tiles.append(t)
        self.grid.set_tiles(tiles)
        self.empty.hide()
        self.grid.show()
        self.decide.setVisible(not self.app.panels_hidden)
        self.controls.show()
        # combine choices
        for box in (self.pic_from, self.snd_from):
            box.blockSignals(True)
            box.clear()
        for k, info in enumerate(infos):
            self.pic_from.addItem(f"{k + 1}. {info['name']}", k)
            if info.get("audio"):
                self.snd_from.addItem(f"{k + 1}. {info['name']}", k)
        self.pic_from.setCurrentIndex(max(0, self.pic_from.findData(bv)))
        if ba is not None:
            self.snd_from.setCurrentIndex(max(0, self.snd_from.findData(ba)))
        for box in (self.pic_from, self.snd_from):
            box.blockSignals(False)
        suggest = ba is not None and ba != bv and (not infos[bv].get("audio") or
                                                    ce.audio_score(infos[ba]) > ce.audio_score(infos[bv]))
        self.combine.blockSignals(True)
        self.combine.setChecked(bool(suggest))
        self.combine.blockSignals(False)
        self.combine.setEnabled(self.snd_from.count() > 0)
        self.combine.setToolTip(("Suggested: copy %d has the best picture, copy %d the best sound. " % (bv + 1, ba + 1)
                                 if suggest else "") + "The picture is copied as it is, never re-encoded.")
        self._load_players()
        self.listen(ba if ba is not None else bv, quiet=True)
        self._decision_changed()
        self.seek(0)
        self.play()

    def _clear(self, text=None):
        self.pause()
        self.release_files(forget=True)
        self.grid.set_tiles([])
        self.grid.hide()
        self.decide.hide()
        self.controls.hide()
        self.data = None
        self.empty.setText(text or "Choose a folder and press Find comparisons.")
        self.empty.show()

    # ----- players -----
    def _load_players(self):
        self.release_files(forget=True)
        if not AVAILABLE:
            return
        self.players = []
        for k, tile in enumerate(self.grid.tiles):
            p = QMediaPlayer(self)
            p.setVideoOutput(tile.view.item)
            p.setSource(QUrl.fromLocalFile(tile.info["path"]))
            p.setPlaybackRate(self.speed)
            self.players.append(p)
        self.audio = QAudioOutput(self)
        self._volume(self.vol.value())

    def release_files(self, forget=False):
        """Stop the players and let go of the files (so they can be recycled or replaced)."""
        for p in self.players:
            try:
                p.stop()
                p.setSource(QUrl())
            except RuntimeError:
                pass
        if forget:
            for p in self.players:
                try:
                    p.deleteLater()
                except RuntimeError:
                    pass
            self.players = []
        self.playing = False
        self.timer.stop()
        self._show_play()

    def _ensure_sources(self):
        for p, tile in zip(self.players, self.grid.tiles):
            if p.source().isEmpty() and Path(tile.info["path"]).exists():
                p.setSource(QUrl.fromLocalFile(tile.info["path"]))

    def listen(self, index, quiet=False):
        if index is None or not self.players or not (0 <= index < len(self.players)):
            return
        if not self.grid.tiles[index].info.get("audio"):
            if not quiet:
                self.app.toast(f"Copy {index + 1} has no sound.", "info")
            return
        for k, p in enumerate(self.players):
            p.setAudioOutput(self.audio if k == index else None)
        self.listen_to = index
        for k, t in enumerate(self.grid.tiles):
            t.listen.setChecked(k == index)
            t.listen.setIcon(icons.icon("sound", theme.ACCENT if k == index else theme.SEC, 16))
        if self.playing:
            self._sync(force=True)
        if not quiet:
            self.app.toast(f"Sound from copy {index + 1}.", "info", 2)

    def _volume(self, value):
        if self.audio is not None:
            self.audio.setVolume(0 if self.muted else value / 100)
        settings.save({"volume": round(value / 100, 2)})

    def toggle_mute(self):
        self.muted = not self.muted
        self._volume(self.vol.value())
        self.mute_btn.setIcon(icons.icon("mute" if self.muted else "sound", theme.TEXT, 16))
        return True

    # ----- the shared timeline -----
    def span(self):
        if not self.data:
            return 0.0
        return max((o + i["duration"] for o, i in zip(self.offsets, self.data["infos"])), default=0.0)

    def _local(self, k, T):
        return T - self.offsets[k]

    def play(self):
        if not self.players:
            return
        self._ensure_sources()
        if self.T >= self.span() - 0.05:
            self.T = 0.0
        self.playing = True
        self.base_T = self.T
        self.clock.start()
        self._sync(force=True)
        self.timer.start()
        self._show_play()

    def pause(self):
        if not self.playing:
            return
        self.T = self._now()
        self.playing = False
        self.timer.stop()
        for p in self.players:
            p.pause()
        self.seek(self.T)
        self._show_play()

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()
        return True

    def _show_play(self):
        self.play_btn.setIcon(icons.icon("pause" if self.playing else "play", theme.TEXT, 18))

    def _now(self):
        if not self.playing:
            return self.T
        # follow the copy being listened to, so its sound never skips; otherwise the clock
        k = self.listen_to
        if k is not None and k < len(self.players):
            p = self.players[k]
            local = self._local(k, self.base_T + self.clock.elapsed() / 1000 * self.speed)
            dur = self.data["infos"][k]["duration"]
            if 0.2 < local < dur - 0.2 and p.playbackState() == QMediaPlayer.PlayingState and p.position() > 0:
                return p.position() / 1000 + self.offsets[k]
        return self.base_T + self.clock.elapsed() / 1000 * self.speed

    def seek(self, T):
        if not self.data:
            return
        self.T = max(0.0, min(T, self.span()))
        self.base_T = self.T
        self.clock.restart()
        self._ensure_sources()
        for k, p in enumerate(self.players):
            local = self._local(k, self.T)
            dur = self.data["infos"][k]["duration"]
            p.setPosition(int(max(0.0, min(local, dur - 0.05)) * 1000))
            if not self.playing:
                p.pause()
        if self.playing:
            self._sync(force=True)
        else:
            self._notes(self.T)
        self._show_time()

    def _notes(self, T):
        for k, tile in enumerate(self.grid.tiles):
            local = self._local(k, T)
            dur = self.data["infos"][k]["duration"]
            tile.view.set_note("" if 0 <= local < dur else
                               f"Starts at {fileops.clock(self.offsets[k])}" if local < 0 else "Ended")

    def _sync(self, force=False):
        T = self._now()
        if T != self.base_T + self.clock.elapsed() / 1000 * self.speed:
            self.base_T, self.T = T, T
            self.clock.restart()
        for k, p in enumerate(self.players):
            local = self._local(k, T)
            dur = self.data["infos"][k]["duration"]
            tile = self.grid.tiles[k]
            if 0 <= local < dur:
                tile.view.set_note("")
                if p.playbackState() != QMediaPlayer.PlayingState:
                    p.setPosition(int(local * 1000))
                    p.play()
                else:
                    drift = p.position() / 1000 - local
                    limit = 0.3 if k == self.listen_to else 0.12
                    if force or abs(drift) > limit:
                        if k != self.listen_to or force:
                            p.setPosition(int(local * 1000))
            else:
                if p.playbackState() == QMediaPlayer.PlayingState:
                    p.pause()
                tile.view.set_note(f"Starts at {fileops.clock(self.offsets[k])}" if local < 0 else "Ended")

    def _tick(self):
        if not self.playing:
            return
        T = self._now()
        if T >= self.span():
            if self.loop:
                self.seek(0)
                return
            self.pause()
            self.seek(self.span())
            return
        self.T = T
        self._sync()
        self._show_time()

    def _show_time(self):
        span = self.span()
        if not self.pos.isSliderDown():
            self.pos.blockSignals(True)
            self.pos.setRange(0, int(span * 1000))
            self.pos.setValue(int(self.T * 1000))
            self.pos.blockSignals(False)
        self.time.setText(f"{fileops.clock(self.T)} / {fileops.clock(span)}")

    def seek_by(self, seconds):
        self.seek(self._now() + seconds)
        return True

    def frame(self, n):
        self.pause()
        fps = 30.0
        if self.data:
            v = self.data["infos"][self.data["best_video"]].get("video") or {}
            fps = v.get("fps") or 30.0
        self.seek(self.T + n / fps)
        return True

    def set_speed(self, step):
        k = SPEEDS.index(self.speed) if self.speed in SPEEDS else 3
        if step == 1 and k == len(SPEEDS) - 1:
            k = -1  # the button cycles round
        self.speed = SPEEDS[max(0, min(len(SPEEDS) - 1, k + step))]
        T = self._now()
        for p in self.players:
            p.setPlaybackRate(self.speed)
        self.base_T, self.T = T, T
        self.clock.restart()
        self.speed_btn.setText(f"{self.speed:g}×")
        self.app.toast(f"Speed {self.speed:g}×", "info", 1)
        return True

    def nudge(self, index, frames):
        info = self.data["infos"][index]
        fps = (info.get("video") or {}).get("fps") or 30.0
        self.offsets[index] += frames / fps
        folder = self.groups[self.index]["folder"]
        st = self.state.setdefault(folder, {})
        st.setdefault("nudge", {})[info["path"]] = round(self.offsets[index] - self.data["offsets"][index], 4)
        self._save_state()
        self.grid.tiles[index].set_offset(self.offsets[index], self.data["sure"][index])
        self.seek(self._now())

    def zoom(self, step):
        for t in self.grid.tiles:
            t.view.zoom_by(1.25 if step > 0 else 0.8)

    def fit(self, actual=False):
        for t in self.grid.tiles:
            t.view.fit()
        return True

    # ----- deciding -----
    def _decision_changed(self, *_a):
        if not self.data:
            return
        tiles = self.grid.tiles
        keep = [t for t in tiles if t.keep.isChecked()]
        drop = [t for t in tiles if not t.keep.isChecked()]
        text = f"Keep {len(keep)} · recycle {len(drop)}"
        combining = self.combine.isChecked() and self.pic_from.count() and self.snd_from.count() and \
            self.pic_from.currentData() != self.snd_from.currentData()
        for w in (self.pic_from, self.snd_from):
            w.setEnabled(self.combine.isChecked())
        if combining:
            p, s = self.pic_from.currentData() + 1, self.snd_from.currentData() + 1
            text += f" · copy {p} gets copy {s}'s sound"
        if self._move_target():
            text += f" · kept ones move to {Path(self._move_target()).name}"
        self.decision.setText(text)
        self.apply_btn.setEnabled(bool(keep) or bool(combining))

    def tick_all(self):
        on = not all(t.keep.isChecked() for t in self.grid.tiles)
        for t in self.grid.tiles:
            t.set_keep(on)

    def apply(self):
        if not self.data or self.index < 0:
            return True
        tiles = self.grid.tiles
        infos = self.data["infos"]
        combining = self.combine.isChecked() and self.pic_from.currentData() is not None and \
            self.snd_from.currentData() is not None and self.pic_from.currentData() != self.snd_from.currentData()
        pic = self.pic_from.currentData() if combining else None
        snd = self.snd_from.currentData() if combining else None
        keep = [k for k, t in enumerate(tiles) if t.keep.isChecked()]
        if combining and pic not in keep:
            keep.append(pic)  # the combined copy is the one kept
        drop = [k for k in range(len(tiles)) if k not in keep]
        if not keep:
            dialogs.info("Keep at least one", "Tick Keep on the copy (or copies) to keep.", icon_name="info")
            return True
        what = []
        if combining:
            what.append(f"Copy {pic + 1} gets copy {snd + 1}'s sound (its picture is copied unchanged).")
        what.append(f"{plural(len(drop), 'copy', 'copies')} go to the Recycle Bin." if drop else "Nothing is recycled.")
        move_to = self._move_target()
        if self.move_on.isChecked() and not move_to:
            dialogs.info("Choose where kept videos go", "Choose a folder for Move kept videos to, or untick it.",
                         icon_name="folder")
            return True
        if move_to:
            root = self.folder.text().strip()
            group_folder = self.groups[self.index]["folder"]
            what.append(f"The kept {'copy moves' if len(keep) == 1 else 'copies move'} to {move_to}" +
                        (", then this comparison's folder goes to the Recycle Bin once it's empty."
                         if Path(group_folder) != Path(root) else "."))
        if (drop or move_to) and not dialogs.ask(
                f"Recycle {plural(len(drop), 'copy', 'copies')}?" if drop else "Move the kept copies?", " ".join(what),
                                    "Apply", kind="danger" if drop else "primary", icon_name="trash",
                                    items=[(infos[k]["name"], "to the Recycle Bin") for k in drop]):
            return True
        job_data = {"infos": infos, "offsets": list(self.offsets), "pic": pic, "snd": snd, "drop": drop,
                    "keep": keep, "folder": self.groups[self.index]["folder"], "move_to": move_to,
                    "root": self.folder.text().strip()}
        self.pause()
        self.release_files(forget=True)
        self.grid.set_tiles([])
        self.empty.setText("Applying…")
        self.empty.show()
        self.grid.hide()
        self.decide.hide()
        self.controls.hide()
        self.app.start(jobs.Job(f"Applying comparison {self.index + 1}", self._apply_job, job_data,
                                short="Applying", done=self._applied,
                                failed=lambda j: (dialogs.error("Couldn't apply it", str(j.error)),
                                                  self.open(self.index))))
        return True

    def _apply_job(self, d, log, progress):
        infos, errors = d["infos"], []
        steps = len(d["drop"]) + (2 if d["pic"] is not None else 0) + (len(d["keep"]) if d.get("move_to") else 0)
        done = 0
        combined = None
        if d["pic"] is not None:
            vi, ai = infos[d["pic"]], infos[d["snd"]]
            src = Path(vi["path"])
            tmp = src.with_name(f".{src.stem}.combining{src.suffix}")
            progress(done, steps, f"Combining copy {d['pic'] + 1}'s picture with copy {d['snd'] + 1}'s sound")
            try:
                ce.combine(vi, ai, d["offsets"][d["pic"]], d["offsets"][d["snd"]], tmp, log)
                done += 1
                progress(done, steps, f"Replacing {src.name}")
                fileops.recycle(src)          # the original goes to the Recycle Bin, never deleted
                tmp.replace(src)
                combined = str(src)
                log(f"Combined: {src.name} now has the sound of {Path(ai['path']).name}. The original is in the "
                    "Recycle Bin.")
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                errors.append(f"Couldn't combine into {src.name}: {exc}")
                log(errors[-1])
            done += 1
        for k in d["drop"]:
            path = Path(infos[k]["path"])
            progress(done, steps, f"Recycling {path.name}")
            if not path.exists():
                log(f"Already gone: {path.name}")
            else:
                try:
                    fileops.recycle(path)
                    log(f"Recycled {path.name}")
                except fileops.RecycleError as exc:
                    errors.append(str(exc))
                    log(f"Skipped: {exc}")
            done += 1
        moved = []
        if d.get("move_to"):
            dest = Path(d["move_to"])
            for k in d["keep"]:
                path = Path(infos[k]["path"])
                if not path.exists():
                    continue
                progress(done, steps, f"Moving {path.name}")
                try:
                    target = fileops.move_file(path, dest)
                    moved.append((str(path), str(target)))
                    log(f"Moved {path.name} → {target}")
                except OSError as exc:
                    errors.append(f"Couldn't move {path.name}: {exc}")
                    log(errors[-1])
                done += 1
            if moved:
                import movelog
                movelog.record("Compare videos", f"Moved {len(moved)} kept video(s) to {dest.name}",
                               [("move", s, t) for s, t in moved])
            folder = Path(d["folder"])
            if folder != Path(d["root"]) and folder.is_dir() and not any(
                    p for p in folder.iterdir() if p.name.lower() not in ("desktop.ini", "thumbs.db", ".ds_store")):
                try:
                    fileops.recycle(folder)
                    log(f"Sent the emptied folder {folder.name} to the Recycle Bin.")
                except fileops.RecycleError as exc:
                    errors.append(str(exc))
                    log(errors[-1])
            elif folder != Path(d["root"]) and folder.is_dir():
                left = [p.name for p in folder.iterdir()][:5]
                log(f"Left the folder {folder.name} where it is: it still has {', '.join(left)}.")
        progress(steps, steps, "Done")
        summary = f"{plural(len(d['drop']) - sum(1 for e in errors if 'Recycle Bin' in e), 'copy', 'copies')} recycled"
        if combined:
            summary = "combined, " + summary
        if moved:
            summary += f", {len(moved)} moved"
        return {"summary": summary, "errors": errors, "folder": d["folder"]}

    def _applied(self, job):
        result = job.result if isinstance(job.result, dict) else {}
        folder = result.get("folder")
        if folder:
            self.state.setdefault(folder, {})["done"] = True
            self._save_state()
        if result.get("errors"):
            dialogs.error("Some files were skipped", "\n".join(result["errors"][:8]))
        row = self.index
        later = [g["folder"] for g in self.groups[row + 1:] + self.groups[:row + 1]
                 if not self.state.get(g["folder"], {}).get("done")]
        if not later:
            self.find(quiet=True)
            self._clear("All done: every comparison here has been applied.")
            self.index = -1
            return
        self.find(quiet=True, select=later[0])

    def _save_state(self):
        try:
            fileops.write_json(_state_file(), self.state)
        except OSError:
            pass

    # ----- keys -----
    def space(self):
        return self.toggle() if self.data else False

    def enter(self):
        if self.data:
            return self.apply()
        return False

    def step(self, delta):
        if not self.groups:
            return False
        if delta == float("-inf"):
            row = 0
        elif delta == float("inf"):
            row = len(self.groups) - 1
        else:
            row = max(0, min(len(self.groups) - 1, self.list.currentRow() + int(delta)))
        self.list.setCurrentRow(row)
        return True

    def updown(self, direction):
        self.vol.setValue(self.vol.value() + 5 * direction)
        if self.muted:
            self.toggle_mute()
        self.app.toast(f"Volume {self.vol.value()}", "info", 1)
        return True

    def key_event(self, key, mods):
        """Keys this screen uses beyond the app's own (see the K list)."""
        if not self.data:
            return False
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        digits = {getattr(Qt, f"Key_{n}"): n for n in range(1, 9)}
        if key in digits:
            k = digits[key] - 1
            if k >= len(self.grid.tiles):
                return True
            if ctrl:
                t = self.grid.tiles[k]
                t.set_keep(not t.keep.isChecked())
            else:
                self.listen(k)
            return True
        if ctrl:
            return False
        if key in (Qt.Key_Left, Qt.Key_Right):
            sign = -1 if key == Qt.Key_Left else 1
            return self.seek_by(sign * (5 if shift else 3))
        if key == Qt.Key_Comma:
            return self.frame(-1)
        if key == Qt.Key_Period:
            return self.frame(1)
        if key == Qt.Key_9:
            return self.frame(-1)
        if key == Qt.Key_0:
            return self.frame(1)
        if key == Qt.Key_BracketLeft:
            return self.set_speed(-1)
        if key == Qt.Key_BracketRight:
            return self.set_speed(1) if self.speed != SPEEDS[-1] else True
        if key == Qt.Key_M:
            return self.toggle_mute()
        if key == Qt.Key_C:
            self.combine.setChecked(not self.combine.isChecked())
            return True
        if key == Qt.Key_Z:
            return self.fit()
        return False

    def set_panels_hidden(self, hidden):
        super().set_panels_hidden(hidden)
        for t in self.grid.tiles:
            t.head.setVisible(not hidden)
        if self.data:
            self.decide.setVisible(not hidden)
        self.grid.arrange(force=True)

    def shown(self):
        self._ensure_sources()

    def hidden(self):
        self.pause()

    def closing(self):
        self.release_files(forget=True)

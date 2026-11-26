"""The window shell (DESIGN.md, "Layout"): a 32 px title bar with status pills, the 64 px rail, the screens,
the 36 px status bar, the log drawer, toasts and the keyboard. On Windows the title bar is drawn by the app
while Windows keeps resizing, snapping and the window shadow working."""
import os
import sys
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea,
                               QStackedWidget, QTabBar, QTextEdit, QToolButton, QVBoxLayout, QWidget)

import dialogs
import fileops
import gpu
import icons
import jobs
import logs
import movelog
import paths
import settings
import theme
import version
from widgets import Bridge, ElidedLabel, button, label, repolish

TITLE_H = 32
RAIL_W = 64
STATUS_H = 36
DRAWER_H = 220
STALL_SECONDS = 20


# ----- title bar -----
class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setObjectName("titlebar")
        self.setFixedHeight(TITLE_H)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 0, 1)
        h.setSpacing(6)
        self.app_name = QLabel("Media Toolbox")
        self.app_name.setObjectName("appname")
        self.screen_name = QLabel("")
        self.screen_name.setObjectName("screenname")
        h.addWidget(self.app_name)
        h.addWidget(self.screen_name)
        h.addStretch(1)
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        h.addLayout(self.pills)
        h.addSpacing(8)
        self.buttons = []
        for name, obj, slot in (("win_min", "winbtn", window.showMinimized),
                                ("win_max", "winbtn", window.toggle_maximized),
                                ("win_close", "winclose", window.close)):
            b = QPushButton()
            b.setObjectName(obj)
            b.setFocusPolicy(Qt.NoFocus)
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(slot)
            b.setProperty("icon_name", name)
            h.addWidget(b)
            self.buttons.append(b)
        self.max_button = self.buttons[1]
        self.refresh_icons()

    def refresh_icons(self):
        for b in self.buttons:
            name = b.property("icon_name")
            if name == "win_max" and self.window_.is_maxed():
                name = "win_restore"
            b.setIcon(icons.icon(name, theme.SEC, 16))
        self.buttons[0].setToolTip("Minimise")
        self.buttons[1].setToolTip("Restore" if self.window_.is_maxed() else "Maximise")
        self.buttons[2].setToolTip("Close")

    def is_drag_area(self, pos):
        """True where dragging moves the window: the strip, except its buttons and pills."""
        child = self.childAt(pos)
        return not isinstance(child, QPushButton)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drag_area(event.position().toPoint()):
            self.window_.toggle_maximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drag_area(event.position().toPoint()):
            self.window_.start_move(event.globalPosition().toPoint())


class Pill(QPushButton):
    """"● Converting 3/12 ▬▬ 25%": a running job on every screen. Clicking opens the log.

    Every part is measured and drawn here (dot, text, bar, percentage), so they never overlap whatever the
    font, text size or UI scale."""
    PAD, DOT, GAP, BAR = 10, 7, 8, 46

    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("pill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.clicked.connect(on_click)
        self.share = None
        self.state = "run"
        self.label = ""

    def set(self, text, share, state="run"):
        self.label, self.share, self.state = text, share, state
        self.setToolTip(text + ("" if share is None else f" \u00b7 {share * 100:.0f}%") + "\nClick to open the log")
        self.updateGeometry()
        self.update()

    def _pct(self):
        return "" if self.share is None else f"{self.share * 100:.0f}%"

    def sizeHint(self):
        fm = self.fontMetrics()
        w = self.PAD + self.DOT + self.GAP + fm.horizontalAdvance(self.label)
        if self.share is not None:
            w += self.GAP + self.BAR + self.GAP + fm.horizontalAdvance("100%")
        return QSize(w + self.PAD + 2, max(22, fm.height() + 6))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        super().paintEvent(event)  # the capsule background and border, from the stylesheet
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = self.fontMetrics()
        mid = self.height() // 2
        colour = {"run": theme.ACCENT, "warn": theme.WARN, "paused": theme.SEC}.get(self.state, theme.ACCENT)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colour))
        x = self.PAD
        p.drawEllipse(x, mid - self.DOT // 2, self.DOT, self.DOT)
        x += self.DOT + self.GAP
        right = self.width() - self.PAD
        if self.share is not None:
            pct_w = fm.horizontalAdvance("100%")
            bar_x = right - pct_w - self.GAP - self.BAR
            text_room = bar_x - self.GAP - x
        else:
            text_room = right - x
        p.setPen(QColor(theme.TEXT if self.underMouse() else theme.SEC))
        p.drawText(QRect(x, 0, max(0, text_room), self.height()), int(Qt.AlignVCenter | Qt.AlignLeft),
                   fm.elidedText(self.label, Qt.ElideRight, max(0, text_room)))
        if self.share is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.RAISED2))
            p.drawRoundedRect(QRect(bar_x, mid - 2, self.BAR, 4), 2, 2)
            p.save()
            p.translate(bar_x, mid - 2)
            p.setBrush(theme.qgradient(self.BAR, 4))
            p.drawRoundedRect(QRect(0, 0, max(2, int(self.BAR * self.share)), 4), 2, 2)
            p.restore()
            p.setPen(QColor(theme.TEXT if self.underMouse() else theme.SEC))
            p.drawText(QRect(right - pct_w, 0, pct_w, self.height()), int(Qt.AlignVCenter | Qt.AlignRight),
                       self._pct())
        p.end()


# ----- rail -----
class Rail(QFrame):
    def __init__(self, window, tools, bottom):
        super().__init__()
        self.window_ = window
        self.setObjectName("rail")
        self.setFixedWidth(RAIL_W)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 8, 4, 8)
        v.setSpacing(2)
        self.logo = LogoTile()
        v.addWidget(self.logo, 0, Qt.AlignHCenter)
        v.addSpacing(8)
        self.buttons = {}
        self.dots = {}
        for key, name, short, icon_name in tools:
            v.addWidget(self._button(key, short, name, icon_name), 0, Qt.AlignHCenter)
        v.addStretch(1)
        for key, name, icon_name in bottom:
            v.addWidget(self._button(key, name, name, icon_name), 0, Qt.AlignHCenter)

    def _button(self, key, text, tip, icon_name):
        b = QToolButton()
        b.setObjectName("railbtn")
        b.setText(text)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(theme.RAIL_ICON, theme.RAIL_ICON))
        b.setFixedWidth(56)
        b.setMinimumHeight(48)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)  # the rail is reached with its keys and the mouse; Tab stays in the screen
        b.setProperty("icon_name", icon_name)
        b.clicked.connect(lambda _c=False, k=key: self.window_.rail_clicked(k))
        dot = QLabel(b)
        dot.setFixedSize(7, 7)
        dot.move(38, 6)
        dot.hide()
        self.buttons[key] = b
        self.dots[key] = dot
        return b

    def set_active(self, key):
        for k, b in self.buttons.items():
            b.setProperty("active", "true" if k == key else "false")
            repolish(b)
        self.refresh_icons()

    def set_attention(self, key, on):
        if key in self.dots:
            self.dots[key].setVisible(on)

    def refresh_icons(self):
        for k, b in self.buttons.items():
            active = b.property("active") == "true"
            b.setIcon(icons.icon(b.property("icon_name"), theme.ACCENT if active else theme.SEC, theme.RAIL_ICON))
        for dot in self.dots.values():
            dot.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 3px;")
        self.logo.update()


class LogoTile(QWidget):
    """The logo tile, in the accent."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 36)
        self.setToolTip(f"Media Toolbox {version.__version__}")

    _cache = {}

    def paintEvent(self, event):
        """The logo on its own in the theme's accent gradient, with a soft shadow (no tile behind it)."""
        dpr = self.devicePixelRatioF()
        key = (tuple(theme.STOPS), theme.ANGLE, dpr)
        pm = self._cache.get(key)
        if pm is None:
            import app_icon
            from PySide6.QtGui import QImage, QPixmap
            px = int(round(36 * dpr))
            img = app_icon.logo_image(px, list(theme.STOPS), theme.ANGLE)
            q = QImage(img.tobytes("raw", "RGBA"), px, px, 4 * px, QImage.Format_RGBA8888).copy()
            pm = QPixmap.fromImage(q)
            pm.setDevicePixelRatio(dpr)
            self._cache.clear()
            self._cache[key] = pm
        p = QPainter(self)
        p.drawPixmap(0, 0, pm)
        p.end()


# ----- status bar -----
class Track(QWidget):
    """The progress track: a gradient fill, or a sliding bar when the size isn't known yet."""

    def __init__(self, width=220):
        super().__init__()
        self.setFixedSize(width, 6)
        self.share = 0.0
        self.sliding = False
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def set(self, share, sliding=False):
        self.share = share or 0.0
        if sliding != self.sliding:
            self.sliding = sliding
            self.timer.start() if sliding else self.timer.stop()
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.RAISED2))
        p.drawRoundedRect(self.rect(), 3, 3)
        p.setBrush(theme.qgradient(self.width(), 6))
        if self.sliding:
            w = self.width() * 0.3
            x = -w + (self.width() + w) * self.phase
            p.drawRoundedRect(QRect(int(x), 0, int(w), 6), 3, 3)
        elif self.share > 0:
            p.drawRoundedRect(QRect(0, 0, max(6, int(self.width() * self.share)), 6), 3, 3)
        p.end()


class GpuChip(QWidget):
    """A 22 px round chip with a tiny load bar, then the GPU's name, load and memory. On the CPU: a warning."""

    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(7)
        self.ring = _ChipRing()
        h.addWidget(self.ring)
        self.text = label("", "caption")
        h.addWidget(self.text)
        self.last_poll = 0
        self.hide()

    def show_gpu(self):
        if time.monotonic() - self.last_poll < 2:
            return
        self.last_poll = time.monotonic()
        stats = gpu.stats()
        if stats:
            self.ring.load = stats["load"] / 100
            self.ring.warn = False
            self.text.setProperty("role", "caption")
            self.text.setText(gpu.chip_text(stats))
        else:
            self.text.setText("GPU details not available")
        repolish(self.text)
        self.ring.update()
        self.show()

    def show_cpu(self):
        self.ring.load = 0
        self.ring.warn = True
        self.text.setProperty("role", "warn")
        self.text.setText("On the CPU (slow)")
        repolish(self.text)
        self.ring.update()
        self.show()


class _ChipRing(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 22)
        self.load = 0.0
        self.warn = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(theme.WARN if self.warn else theme.LINE2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(1, 1, 20, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.RAISED2))
        p.drawRoundedRect(6, 10, 10, 3, 1, 1)
        if self.load:
            p.setBrush(theme.qgradient(10, 3))
            p.drawRoundedRect(6, 10, max(1, int(10 * self.load)), 3, 1, 1)
        p.end()


class StatusBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setObjectName("statusbar")
        self.setFixedHeight(STATUS_H)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 8, 0)
        h.setSpacing(12)
        self.job = label("Ready", "heading")
        self.what = ElidedLabel("Nothing running")
        h.addWidget(self.job)
        h.addWidget(self.what, 1)
        self.track = Track()
        h.addWidget(self.track)
        self.pct = label("", "value")
        self.pct.setMinimumWidth(36)
        self.pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pct.setStyleSheet("font-weight: 600;")
        h.addWidget(self.pct)
        self.times = label("", "muted")
        h.addWidget(self.times)
        self.chip = GpuChip()
        h.addWidget(self.chip)
        self.next_btn = button("")
        self.next_btn.hide()
        h.addWidget(self.next_btn)
        self.pause_btn = button("Pause", icon=icons.icon("pause", theme.TEXT, 16))
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.hide()
        h.addWidget(self.pause_btn)
        self.stop_btn = button("Stop", icon=icons.icon("stop", theme.TEXT, 16),
                               tip="Stop this job and empty the queue. Finished work is kept.")
        self.stop_btn.clicked.connect(lambda: window.queue.stop())
        self.stop_btn.hide()
        h.addWidget(self.stop_btn)
        self.log_btn = button("Log", "ghost", icon=icons.icon("log", theme.SEC, 16), tip="Open or close the log (L)")
        self.log_btn.clicked.connect(window.toggle_drawer)
        h.addWidget(self.log_btn)
        self._next_fn = None
        self.next_btn.clicked.connect(lambda: self._next_fn and self._next_fn())
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        theme.on_change(self._recolour)
        self.refresh()

    def _recolour(self):
        self.pause_btn.setIcon(icons.icon("pause" if not self._paused() else "play", theme.TEXT, 16))
        self.stop_btn.setIcon(icons.icon("stop", theme.TEXT, 16))
        self.log_btn.setIcon(icons.icon("log", theme.SEC, 16))
        self.track.update()

    def _paused(self):
        job = self.window_.queue.current
        return bool(job and job.paused)

    def _toggle_pause(self):
        job = self.window_.queue.current
        if not job or not job.pause_target:
            return
        if job.paused:
            job.resume()
            self.window_.log("Continued.")
        else:
            job.pause()
            self.window_.log("Paused. Keep the app open; click Continue to carry on.")
        self._recolour()
        self.refresh()

    def refresh(self):
        queue = self.window_.queue
        job = queue.current
        waiting = len(queue.waiting)
        if job is None:
            self._show_idle(queue.last)
            self.window_.update_pills(None, 0)
            return
        share = job.fraction()
        sliding = share is None
        shown = None if sliding else min(share, 0.99)  # capped until truly finished
        self.job.setText(job.title)
        what = job.what
        if job.size and job.total:
            speed = job.speed()
            what = (f"{what} · {fileops.human_size(job.done_count)} of {fileops.human_size(job.total)}"
                    + (f" · {fileops.human_size(speed)}/s" if speed else ""))
        elif job.size:
            what = f"{what} · size not known yet · {fileops.human_size(job.done_count)} so far"
        elif sliding:
            what = f"{what} · size not known yet"
        if waiting:
            what += f" · {waiting} more queued"
        stalled = job.stalled_for()
        warn = stalled >= STALL_SECONDS
        if warn:
            what += f" · no progress for {fileops.clock(stalled)}, the log shows what is running"
        self.what.setText(what)
        self.track.set(shown or 0.0, sliding)
        self.track.show()
        self.pct.setText("—" if sliding else f"{shown * 100:.0f}%")
        self.pct.show()
        elapsed = fileops.clock(job.elapsed())
        left = job.time_left()
        if job.paused:
            times = f"Paused · {elapsed} elapsed"
        elif warn:
            times = f"{elapsed} elapsed · time left unknown"
        elif left is None:
            times = f"{elapsed} elapsed · working out time left…"
        else:
            times = f"{elapsed} elapsed · about {fileops.clock(left)} left"
        self.times.setText(times)
        self.times.setProperty("role", "warn" if warn else "muted")
        repolish(self.times)
        self.times.show()
        if job.gpu == "gpu":
            self.chip.show_gpu()
        elif job.gpu == "cpu":
            self.chip.show_cpu()
        else:
            self.chip.hide()
        self.pause_btn.setVisible(job.pause_target is not None)
        self.pause_btn.setText("Continue" if job.paused else "Pause")
        self.stop_btn.show()
        self.next_btn.hide()
        self.window_.update_pills(job, waiting, shown, "warn" if warn else "paused" if job.paused else "run")

    def _show_idle(self, last):
        self.track.set(0, False)
        self.chip.hide()
        self.pause_btn.hide()
        self.stop_btn.hide()
        self.times.setProperty("role", "muted")
        repolish(self.times)
        if last is None:
            self.job.setText("Ready")
            self.what.setText("Nothing running")
            self.track.hide()
            self.pct.hide()
            self.times.hide()
            self.next_btn.hide()
            return
        took = fileops.clock(last.elapsed())
        if last.finished == "done":
            self.job.setText(f"Finished: {last.summary}" if last.summary else f"Finished: {last.title}")
            self.what.setText(f"took {took}")
            self.track.set(1.0)
            self.pct.setText("100%")
        elif last.finished == "stopped":
            self.job.setText(f"Stopped: {last.title}")
            self.what.setText(f"after {took} · work finished before stopping is kept")
            self.track.set(last.fraction() or 0)
            self.pct.setText("")
        else:
            self.job.setText(f"Failed: {last.title}")
            self.what.setText(f"{last.error} · the log has the details")
            self.track.set(0)
            self.pct.setText("")
        self.track.show()
        self.pct.show()
        self.times.hide()
        if last.next_step and last.finished == "done":
            self.next_btn.setText(last.next_step[0])
            self._next_fn = last.next_step[1]
            self.next_btn.show()
        else:
            self.next_btn.hide()


# ----- the log drawer -----
class LogDrawer(QFrame):
    """Slides up over the bottom of the screen: the activity log, and the move log with Undo."""

    def __init__(self, window):
        super().__init__(window.content_host)
        self.window_ = window
        self.setObjectName("drawer")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 8)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.addTab("Activity")
        self.tabs.addTab("Moves")
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._tab)
        head.addWidget(self.tabs)
        head.addStretch(1)
        self.file_label = ElidedLabel("", "caption", Qt.ElideMiddle)
        head.addWidget(self.file_label, 1)
        self.copy_btn = button("Copy", "ghost", tip="Copy the log to the clipboard")
        self.copy_btn.clicked.connect(self._copy)
        self.clear_btn = button("Clear", "ghost", tip="Clear what's shown here (the file on disk stays)")
        self.clear_btn.clicked.connect(self._clear)
        close = button("Close", "ghost", tip="Close the log (L or Esc)")
        close.clicked.connect(window.toggle_drawer)
        for b in (self.copy_btn, self.clear_btn, close):
            head.addWidget(b)
        v.addLayout(head)
        self.stack = QStackedWidget()
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        self.stack.addWidget(self.text)
        self.moves = MovesList(window)
        self.stack.addWidget(self.moves)
        v.addWidget(self.stack, 1)
        self.hide()

    def _tab(self, i):
        self.stack.setCurrentIndex(i)
        self.copy_btn.setVisible(i == 0)
        self.clear_btn.setVisible(i == 0)
        if i == 1:
            self.moves.reload()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        self.window_.toast("Copied the log.", "ok")

    def _clear(self):
        self.text.clear()

    def show_moves(self):
        self.tabs.setCurrentIndex(1)


class MovesList(QScrollArea):
    """Every logged move, newest first, each with Undo."""

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.v = QVBoxLayout(self.host)
        self.v.setContentsMargins(0, 0, 4, 0)
        self.v.setSpacing(0)
        self.setWidget(self.host)
        movelog.on_change(lambda: window.on_main(self.reload))

    def reload(self):
        while self.v.count():
            item = self.v.takeAt(0)
            if item.widget():
                item.widget().hide()  # hidden at once, so the old rows never show under the new ones
                item.widget().deleteLater()
        entries = movelog.entries()
        if not entries:
            self.v.addWidget(label("No moves yet. Every move a tool makes is listed here, with Undo.", "empty"))
        for e in entries[:200]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 3, 0, 3)
            h.setSpacing(10)
            h.addWidget(label(e["time"][5:16], "caption"))
            n = len(e["items"])
            text = ElidedLabel(f"{e['title']} · {n} file{'s' if n != 1 else ''} · "
                               f"{e['items'][0]['src']} → {e['items'][0]['dst']}"
                               + (f" and {n - 1} more" if n > 1 else ""), "value", Qt.ElideMiddle)
            h.addWidget(text, 1)
            if e.get("undone"):
                h.addWidget(label(e.get("note") or "Undone", "caption"))
            else:
                b = button("Undo", "ghost", icon=icons.icon("undo", theme.SEC, 16))
                b.clicked.connect(lambda _c=False, i=e["id"]: self.window_.undo_move(i))
                h.addWidget(b)
            self.v.addWidget(row)
        self.v.addStretch(1)


# ----- the main window -----
class MainWindow(QMainWindow):
    MIN_W, MIN_H = 1100, 680

    def __init__(self, tools, bottom, safe_mode=False):
        """tools: [(key, name, short label, icon, page class)]; bottom: [(key, name, icon, page class or None)]."""
        super().__init__()
        self.safe_mode = safe_mode
        self.frameless = not safe_mode  # safe mode uses the standard Windows title bar
        self._maxed = False
        self._normal_geometry = None
        self._cursor_shape = None
        self.native = False  # Windows keeps the frame's behaviour (snap, drag to the top, shadow); the app draws it
        self.setWindowTitle("Media Toolbox")
        self.bridge = Bridge()
        self.queue = jobs.JobQueue(self.log, self.on_main)
        self.queue.changed.connect(self._queue_changed)
        self.pages = {}
        self.page_titles = {}
        self.current_key = None
        self.panels_hidden = False
        self._previous_key = None
        self._build(tools, bottom)
        dialogs.set_host(self.root)
        from keys_popup import KeysPopup
        self.keys_popup = KeysPopup(self.root, lambda: getattr(self.page(), "own_keys", None))
        self.toasts = dialogs.Toasts(self.content_host, bottom_offset=STATUS_H + 8)
        theme.on_change(self._recolour)
        if self.frameless:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
                                | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        if self.frameless and sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            try:
                _native_frame(int(self.winId()))
                self.native = True
            except Exception as exc:
                logs.write(f"Couldn't hand the window frame to Windows ({exc}); resizing is done by the app.")
        if self.frameless and not self.native:
            self._edge_timer = QTimer(self)
            self._edge_timer.setInterval(60)
            self._edge_timer.timeout.connect(self._edge_cursor)
            self._edge_timer.start()
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self._restore_geometry()
        self._frame_changed()
        QApplication.instance().installEventFilter(self)

    # ----- building -----
    def _build(self, tools, bottom):
        self.root = QWidget()
        self.root.setObjectName("root")
        self.root.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self.root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.titlebar = TitleBar(self)
        self.titlebar.setVisible(self.frameless)
        v.addWidget(self.titlebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.rail = Rail(self, [(k, n, s, i) for k, n, s, i, _c in tools], [(k, n, i) for k, n, i, _c in bottom])
        body.addWidget(self.rail)
        self.content_host = QWidget()
        cv = QVBoxLayout(self.content_host)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.banner_host = QVBoxLayout()
        self.banner_host.setContentsMargins(theme.PAGE, theme.PAGE, theme.PAGE, 0)
        self.banner_host.setSpacing(theme.GAP)
        cv.addLayout(self.banner_host)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        self.status = StatusBar(self)
        cv.addWidget(self.status)
        body.addWidget(self.content_host, 1)
        v.addLayout(body, 1)
        self.setCentralWidget(self.root)
        self.drawer = LogDrawer(self)
        self.content_host.installEventFilter(self)
        for key, name, _short, _icon, cls in tools:
            self._add_page(key, name, cls)
        for key, name, _icon, cls in bottom:
            if cls is not None:
                self._add_page(key, name, cls)
        self.rail.set_active(None)

    def _add_page(self, key, name, cls):
        holder = QWidget()
        holder.setObjectName("pagehost")
        holder.setFocusPolicy(Qt.ClickFocus)  # takes focus when shown, so no button wears a focus ring at start
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(theme.PAGE, theme.PAGE - 2, theme.PAGE, theme.PAGE)
        page = cls(self)
        hl.addWidget(page)
        self.stack.addWidget(holder)
        self.pages[key] = page
        self.page_titles[key] = name

    def add_banner(self, widget):
        self.banner_host.addWidget(widget)

    # ----- pages -----
    def rail_clicked(self, key):
        if key == "log":
            self.toggle_drawer()
        elif key == "keys":
            self.keys_popup.toggle()
        else:
            self.show_page(key)

    def show_page(self, key):
        if key not in self.pages:
            return
        if key != self.current_key:
            self._previous_key = self.current_key
            old = self.pages.get(self.current_key)
            if old is not None and hasattr(old, "hidden"):
                old.hidden()  # e.g. Compare pauses its videos when you leave it
        self.current_key = key
        self.stack.setCurrentWidget(self.pages[key].parentWidget())
        self.rail.set_active(key)
        self.titlebar.screen_name.setText("·  " + self.page_titles[key])
        self.setWindowTitle(f"Media Toolbox · {self.page_titles[key]}")
        self.pages[key].set_panels_hidden(self.panels_hidden)
        self.pages[key].parentWidget().setFocus()
        self.pages[key].shown()
        settings.save({"last_page": key})

    def page(self):
        return self.pages.get(self.current_key)

    def set_attention(self, key, on):
        self.rail.set_attention(key, on)

    # ----- jobs -----
    def start(self, job):
        """Run a job now, or add it to the queue when another one is running."""
        queued = self.queue.busy()
        self.queue.add(job)
        if queued:
            self.toast(f"Added to the queue: {job.title}", "info")
        return job

    def _queue_changed(self):
        busy = self.queue.busy()
        for page in self.pages.values():
            try:
                page.queue_changed(busy)
            except Exception as exc:
                self.log(f"ERROR: {exc}")
        self.status.refresh()

    def update_pills(self, job, waiting, share=None, state="run"):
        layout = self.titlebar.pills
        while layout.count() < 1:
            layout.addWidget(Pill(self.toggle_drawer))
        pill = layout.itemAt(0).widget()
        if job is None:
            pill.hide()
            return
        count = f" {job.done_count}/{job.total}" if job.total and not job.size else ""
        pill.set(f"{job.short}{count}" + (f" · +{waiting}" if waiting else ""), share, state)
        pill.show()

    # ----- log, toasts, thread-safe calls -----
    def log(self, msg):
        line = str(msg)
        logs.write(line)
        self.on_main(lambda: self._append_log(line))

    def _append_log(self, line):
        self.drawer.text.appendPlainText(f"{time.strftime('%H:%M:%S')}  {line}")
        if line.startswith("ERROR") and not self.drawer.isVisible():
            self.toggle_drawer(True)  # a failure should never go unseen

    def on_main(self, fn):
        """Run fn on the UI thread (safe to call from background threads)."""
        self.bridge.call.emit(fn)

    def toast(self, text, kind="ok", seconds=5):
        self.on_main(lambda: self.toasts.show(text, kind, seconds))

    def toggle_drawer(self, show=None):
        visible = self.drawer.isVisible()
        show = (not visible) if show is None else show
        if show == visible:
            return
        self._place_drawer()
        end = self.drawer.geometry()
        start = QRect(end.x(), end.y() + 40, end.width(), end.height())
        if show:
            self.drawer.setGeometry(start)
            self.drawer.show()
            self.drawer.raise_()
            self.drawer.file_label.setText(str(logs.run_log_path() or ""))
            anim = QPropertyAnimation(self.drawer, b"geometry", self)
            anim.setDuration(180)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._drawer_anim = anim
        else:
            self.drawer.hide()
        self.rail.buttons["log"].setProperty("active", "true" if show else "false")
        self.rail.set_active(self.current_key) if not show else repolish(self.rail.buttons["log"])

    def _place_drawer(self):
        h = self.content_host
        self.drawer.setGeometry(0, h.height() - STATUS_H - DRAWER_H, h.width(), DRAWER_H)

    def undo_move(self, entry_id=None):
        entry = movelog.last_undoable() if entry_id is None else next(
            (e for e in movelog.entries() if e["id"] == entry_id), None)
        if entry is None:
            self.toast("There's no move to undo.", "info")
            return
        done, problems = movelog.undo(entry["id"], self.log)
        if problems:
            dialogs.info("Undo finished with problems", f"{done} file(s) went back. Some couldn't:",
                         items=problems, icon_name="warn")
        else:
            self.toast(f"Undone: {entry['title']} ({done} file{'s' if done != 1 else ''} put back)", "ok")
        for page in self.pages.values():
            if hasattr(page, "after_undo"):
                page.after_undo(entry)

    # ----- look -----
    def _recolour(self):
        self.rail.refresh_icons()
        self.titlebar.refresh_icons()
        self.update()

    # ----- window -----
    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self._frame_changed()
        super().changeEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._maxed:
                self.setGeometry(self.screen().availableGeometry())
            self.titlebar.setVisible(self.frameless)
        else:
            self.titlebar.setVisible(False)  # full screen hides the strip
            self.showFullScreen()
        self._frame_changed()

    def toggle_panels(self):
        self.panels_hidden = not self.panels_hidden
        self.rail.setVisible(not self.panels_hidden and not settings.load().get("rail_hidden", False))
        if self.page():
            self.page().set_panels_hidden(self.panels_hidden)

    def toggle_rail(self):
        hidden = not settings.load().get("rail_hidden", False)
        settings.save({"rail_hidden": hidden})
        self.rail.setVisible(not hidden)

    def _restore_geometry(self):
        from PySide6.QtCore import QByteArray
        saved = settings.load().get("window")
        if saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode()))
        else:
            self.resize(1440, 900)
        # never open off screen or bigger than the screen (a monitor may have been unplugged)
        avail = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        geo = self.geometry()
        if not avail.intersects(geo) or geo.width() > avail.width() or geo.height() > avail.height():
            w, h = min(geo.width(), avail.width()), min(geo.height(), avail.height())
            self.setGeometry(avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 2, w, h)
        if settings.load().get("window_maxed") and self.native:
            QTimer.singleShot(0, self.showMaximized)
        elif settings.load().get("window_maxed") and self.frameless and sys.platform == "win32":
            self._normal_geometry = self.geometry()
            self._maxed = True
            self.setGeometry(avail)
        self.rail.setVisible(not settings.load().get("rail_hidden", False))

    def eventFilter(self, obj, event):
        if obj is self.content_host and event.type() == QEvent.Resize and self.drawer.isVisible():
            self._place_drawer()
        if (event.type() == QEvent.MouseButtonPress and self.frameless and event.button() == Qt.LeftButton
                and isinstance(obj, QWidget) and obj.window() is self):
            edges = self._edges_at(event.globalPosition().toPoint())
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                return True
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            return self._key(event)
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.BackButton
                and isinstance(obj, QWidget) and obj.window() is self):
            page = self.page()  # the mouse's back button leaves Gallery for the view you came from
            if page is not None and hasattr(page, "leave_full_view") and page.leave_full_view():
                return True
        return False

    def closeEvent(self, event):
        if self.queue.busy():
            if not dialogs.ask("Stop the running job and close?", f"{self.queue.current.title} is still running. "
                               "Work finished so far is kept.", "Stop and close", kind="danger"):
                event.ignore()
                return
            self.queue.stop()
        if not getattr(self, "reset_on_close", False):
            if self._maxed and self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)  # save the normal size, and that it was maximised
            settings.save({"window": bytes(self.saveGeometry().toBase64()).decode(),
                           "window_maxed": self._maxed or (self.native and self.isMaximized())})
        for page in self.pages.values():
            if hasattr(page, "closing"):
                page.closing()
        logs.end_session()
        event.accept()

    # ----- keyboard (STANDARDS.md, "Keyboard") -----
    def _typing(self):
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)):
            return not (isinstance(w, QPlainTextEdit) and w.isReadOnly())
        return isinstance(w, QComboBox) and w.isEditable()

    def _key(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if self.keys_popup.isVisible():
            if key in (Qt.Key_Escape, Qt.Key_K) and not ctrl:
                self.keys_popup.close_popup()
            return True  # while the shortcuts are showing, other keys do nothing
        if dialogs.host() is not None and any(c.objectName() == "scrim" and c.isVisible()
                                               for c in self.root.children() if isinstance(c, QWidget)):
            return False  # a dialog is open: it handles its own keys
        if key == Qt.Key_Escape:
            return self._escape()
        typing = self._typing()
        page = self.page()
        if ctrl and shift and key == Qt.Key_I:
            self.copy_debug_report()
            return True
        if ctrl and key == Qt.Key_F:
            return self._focus_filter()
        if ctrl and key == Qt.Key_Z and not typing:
            self.undo_move()
            return True
        if ctrl and key == Qt.Key_A and not typing:
            if page:
                page.tick_all()
            return True
        if page is not None and hasattr(page, "key_event") and not typing and not (mods & Qt.AltModifier):
            if page.key_event(key, mods):
                return True
        if ctrl or (mods & Qt.AltModifier) or typing:
            return False
        in_list = isinstance(QApplication.focusWidget(), QAbstractItemView)
        letters = {Qt.Key_K: self.keys_popup.toggle, Qt.Key_S: lambda: self.show_page("settings"),
                   Qt.Key_L: self.toggle_drawer, Qt.Key_M: self.toggle_rail, Qt.Key_H: self.toggle_panels,
                   Qt.Key_F: self.toggle_fullscreen, Qt.Key_F11: self.toggle_fullscreen}
        if key in letters:
            letters[key]()
            return True
        if key == Qt.Key_Slash:
            return self._focus_filter()
        if page is None:
            return False
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            page.zoom(1)
            return True
        if key == Qt.Key_Minus:
            page.zoom(-1)
            return True
        if key in (Qt.Key_0, Qt.Key_1) and hasattr(page, "fit"):
            return bool(page.fit(key == Qt.Key_1))
        if key == Qt.Key_Space and hasattr(page, "space"):
            return bool(page.space())
        if key in (Qt.Key_Return, Qt.Key_Enter) and hasattr(page, "enter"):
            if page.enter():
                return True
        if key == Qt.Key_T and hasattr(page, "toggle_gallery"):
            if page.toggle_gallery():
                return True
        if in_list:
            return False  # lists move with their own arrow keys
        steps = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_PageUp: -1, Qt.Key_PageDown: 1,
                 Qt.Key_Home: float("-inf"), Qt.Key_End: float("inf")}
        if key in steps:
            return bool(page.step(steps[key]))
        if key in (Qt.Key_Up, Qt.Key_Down) and hasattr(page, "updown"):
            return bool(page.updown(1 if key == Qt.Key_Up else -1))
        return False

    def _focus_filter(self):
        page = self.page()
        box = getattr(page, "filter_box", None) if page else None
        if box is None:
            self.toast("This screen has no search or filter box.", "info", 4)
            return True
        box.setFocus()
        if isinstance(box, QLineEdit):
            box.selectAll()
        return True

    def _escape(self):
        """Close or leave, innermost first: full view, full screen, the log, hidden panels, a focused box."""
        page = self.page()
        if page and hasattr(page, "leave_full_view") and page.leave_full_view():
            return True
        if self.isFullScreen():
            self.toggle_fullscreen()
            return True
        if self.drawer.isVisible():
            self.toggle_drawer(False)
            return True
        if self.panels_hidden:
            self.toggle_panels()
            return True
        if self._typing():
            QApplication.focusWidget().clearFocus()
            return True
        return False

    def copy_debug_report(self):
        """Ctrl+Shift+I: a report for bug reports (versions, places, settings), copied to the clipboard."""
        import platform
        from PySide6 import __version__ as pyside
        lines = [f"Media Toolbox {version.__version__}", f"Python {platform.python_version()} · PySide6 {pyside}",
                 f"Windows: {platform.platform()}", f"Safe mode: {self.safe_mode}", ""]
        for place in paths.PLACES:
            lines.append(f"{place.title}: {place.path()}" + (" (drive missing)" if place.missing() else ""))
        lines += ["", "Last log lines:"] + logs.recent_lines()[-30:]
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.toast("Copied a debug report for bug reports.", "ok")

    # ----- own title bar: Qt draws the whole window, Windows draws no frame at all -----
    def _edges_at(self, global_pos):
        """Which window edges the pointer is on (for resizing), or 0."""
        if not self.frameless or self.native or self.is_maxed() or self.isFullScreen():
            return Qt.Edges()
        p = self.mapFromGlobal(global_pos)
        x, y, w, h = p.x(), p.y(), self.width(), self.height()
        if not (-2 <= x <= w + 2 and -2 <= y <= h + 2):
            return Qt.Edges()
        e = Qt.Edges()
        if x < EDGE:
            e |= Qt.LeftEdge
        elif x >= w - EDGE:
            e |= Qt.RightEdge
        if y < EDGE:
            e |= Qt.TopEdge
        elif y >= h - EDGE:
            e |= Qt.BottomEdge
        return e

    def _edge_cursor(self):
        """Show a resize pointer near the edges (checked on a timer, so no widget needs mouse tracking)."""
        if not self.isActiveWindow() or QApplication.mouseButtons() != Qt.NoButton:
            return
        e = self._edges_at(QCursor.pos())
        shape = None
        if e in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            shape = Qt.SizeFDiagCursor
        elif e in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            shape = Qt.SizeBDiagCursor
        elif e in (Qt.LeftEdge, Qt.RightEdge):
            shape = Qt.SizeHorCursor
        elif e in (Qt.TopEdge, Qt.BottomEdge):
            shape = Qt.SizeVerCursor
        if shape != self._cursor_shape:
            if self._cursor_shape is not None:
                QApplication.restoreOverrideCursor()
            if shape is not None:
                QApplication.setOverrideCursor(shape)
            self._cursor_shape = shape

    def is_maxed(self):
        return self._maxed or self.isMaximized()

    def toggle_maximized(self):
        if self.native or not (self.frameless and sys.platform == "win32"):
            self.showNormal() if self.isMaximized() else self.showMaximized()
            return
        # A frameless window maximised by Windows would cover the taskbar, so the app fills the screen's work
        # area itself and remembers the size to go back to.
        if self._maxed:
            self._maxed = False
            self.setGeometry(self._normal_geometry)
        else:
            self._normal_geometry = self.geometry()
            self._maxed = True
            self.setGeometry(self.screen().availableGeometry())
        self._frame_changed()

    def start_move(self, global_pos):
        if self.native:
            if self.windowHandle():
                self.windowHandle().startSystemMove()  # Windows snaps, maximises at the top, restores on drag
            return
        if self._maxed:
            # dragging a maximised window: back to its normal size, under the pointer
            ratio = (global_pos.x() - self.x()) / max(1, self.width())
            self.toggle_maximized()
            self.move(int(global_pos.x() - self.width() * ratio), global_pos.y() - TITLE_H // 2)
        if self.windowHandle():
            self.windowHandle().startSystemMove()

    def _frame_changed(self):
        """The 1 px edge shows only when the window isn't filling the screen."""
        edge = 0 if (self.is_maxed() or self.isFullScreen() or not self.frameless or self.native) else 1
        self.root.layout().setContentsMargins(edge, edge, edge, edge)
        self.root.setProperty("framed", "true" if edge else "false")
        repolish(self.root)
        self.titlebar.refresh_icons()

    def nativeEvent(self, event_type, message):
        if not self.native:
            return False, 0
        try:
            return _native_event(self, message)
        except Exception:
            return False, 0


EDGE = 6  # px from the window's edge that resize it


# ----- Windows: the app draws the title bar, Windows keeps the frame's behaviour -----
# The window keeps WS_THICKFRAME, WS_CAPTION and the maximise box, so Windows still snaps it to the screen's
# edges and corners, maximises it when it's dragged to the top, restores it when a maximised window is
# dragged, and gives it a shadow. WM_NCCALCSIZE makes the whole window client area (so Windows draws no
# frame), and WM_NCHITTEST tells Windows where the edges and the draggable title strip are.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
    GWL_STYLE = -16
    WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = (0x00C00000, 0x00040000, 0x00020000,
                                                                           0x00010000, 0x00080000)
    WVR_REDRAW = 0x0300
    HTCAPTION = 2
    HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = (10, 11, 12, 13, 14, 15,
                                                                                         16, 17)

    class _MARGINS(ctypes.Structure):
        _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class _APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                    ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]

    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.IsZoomed.argtypes = [wintypes.HWND]

    def _native_frame(hwnd):
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
        _user32.SetWindowLongW(hwnd, GWL_STYLE,
                               style | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        margins = _MARGINS(-1, -1, -1, -1)  # the window's shadow
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))

    def _metric(hwnd, index):
        try:
            dpi = _user32.GetDpiForWindow(wintypes.HWND(hwnd))
            return _user32.GetSystemMetricsForDpi(index, dpi)
        except Exception:
            return _user32.GetSystemMetrics(index)

    def _border(hwnd, horizontal):
        """The resize border Windows adds around a maximised window (it hangs off the screen)."""
        value = _metric(hwnd, 32 if horizontal else 33) + _metric(hwnd, 92)  # SM_CXSIZEFRAME + SM_CXPADDEDBORDER
        return value if value > 0 else 8

    def _taskbar_autohides():
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        return bool(ctypes.windll.shell32.SHAppBarMessage(4, ctypes.byref(data)) & 1)  # ABM_GETSTATE, ABS_AUTOHIDE

    def _native_event(window, message):
        msg = wintypes.MSG.from_address(int(message))
        if not msg.hWnd:
            return False, 0
        if msg.message == WM_NCCALCSIZE:
            if msg.wParam:
                rect = _NCCALCSIZE_PARAMS.from_address(msg.lParam).rgrc[0]
            else:
                rect = wintypes.RECT.from_address(msg.lParam)
            if _user32.IsZoomed(msg.hWnd) and not window.isFullScreen():
                tx, ty = _border(msg.hWnd, True), _border(msg.hWnd, False)
                rect.left += tx
                rect.right -= tx
                rect.top += ty
                rect.bottom -= ty
                if _taskbar_autohides():
                    rect.bottom -= 2  # leave a sliver so an auto-hiding taskbar can still pop up
            return True, (WVR_REDRAW if msg.wParam else 0)
        if msg.message == WM_NCHITTEST:
            pos = QCursor.pos()
            x, y = pos.x() - window.x(), pos.y() - window.y()
            w, h = window.frameGeometry().width(), window.frameGeometry().height()
            if not window.isMaximized() and not window.isFullScreen():
                left, right, top, bottom = x < EDGE, x > w - EDGE, y < EDGE, y > h - EDGE
                for hit, code in (((top and left), HTTOPLEFT), ((top and right), HTTOPRIGHT),
                                  ((bottom and left), HTBOTTOMLEFT), ((bottom and right), HTBOTTOMRIGHT),
                                  (left, HTLEFT), (right, HTRIGHT), (top, HTTOP), (bottom, HTBOTTOM)):
                    if hit:
                        return True, code
            bar = window.titlebar
            if bar.isVisible():
                local = bar.mapFromGlobal(pos)
                if bar.rect().contains(local) and bar.is_drag_area(local):
                    return True, HTCAPTION  # Windows drags, snaps and double-click-maximises from here
            return False, 0
        return False, 0
else:
    def _native_frame(hwnd):
        raise RuntimeError("only on Windows")

    def _native_event(window, message):
        return False, 0

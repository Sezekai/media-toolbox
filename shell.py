"""The window shell (DESIGN.md, "Layout"): a 32 px title bar with status pills, the 64 px rail, the screens,
the 36 px status bar, the log drawer, toasts and the keyboard. On Windows the title bar is drawn by the app
while Windows keeps resizing, snapping and the window shadow working."""
import sys
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath
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
            if name == "win_max" and self.window_.isMaximized():
                name = "win_restore"
            b.setIcon(icons.icon(name, theme.SEC, 16))
        self.buttons[0].setToolTip("Minimise")
        self.buttons[1].setToolTip("Restore" if self.window_.isMaximized() else "Maximise")
        self.buttons[2].setToolTip("Close")

    def is_drag_area(self, pos):
        """True where dragging moves the window: the strip, except its buttons and pills."""
        child = self.childAt(pos)
        return not isinstance(child, QPushButton)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drag_area(event.position().toPoint()):
            self.window_.toggle_maximized()

    def mousePressEvent(self, event):
        # Off Windows (and with the system frame) the strip still drags the window.
        if event.button() == Qt.LeftButton and not self.window_.native_frame and self.window_.windowHandle():
            self.window_.windowHandle().startSystemMove()


class Pill(QPushButton):
    """"● Converting 3/12 · 25%": a running job on every screen. Clicking opens the log."""

    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("pill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.clicked.connect(on_click)
        self.share = None
        self.state = "run"
        self.setMinimumWidth(80)

    def set(self, text, share, state="run"):
        self.share, self.state = share, state
        self.setText("      " + text + ("" if share is None else f"      {share * 100:.0f}%"))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colour = {"run": theme.ACCENT, "warn": theme.WARN, "paused": theme.SEC}.get(self.state, theme.ACCENT)
        p.setBrush(QColor(colour))
        p.setPen(Qt.NoPen)
        p.drawEllipse(10, self.height() // 2 - 3, 7, 7)
        if self.share is not None:
            fm = self.fontMetrics()
            pct = f"{self.share * 100:.0f}%"
            x = self.width() - 10 - fm.horizontalAdvance(pct) - 52
            r = QRect(x, self.height() // 2 - 2, 46, 4)
            p.setBrush(QColor(theme.RAISED2))
            p.drawRoundedRect(r, 2, 2)
            p.setBrush(theme.qgradient(46, 4))
            p.save()
            p.translate(x, self.height() // 2 - 2)
            p.drawRoundedRect(QRect(0, 0, max(2, int(46 * self.share)), 4), 2, 2)
            p.restore()
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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, 36, 36, 8, 8)
        p.fillPath(path, theme.qgradient(36, 36))
        p.drawPixmap(8, 8, icons.pixmap("logo", theme.ON_ACCENT, 20))
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
        self.native_frame = sys.platform == "win32" and not safe_mode
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
        self.toasts = dialogs.Toasts(self.content_host, bottom_offset=STATUS_H + 8)
        theme.on_change(self._recolour)
        if self.native_frame:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
                                | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        elif sys.platform != "win32":
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self._restore_geometry()
        QApplication.instance().installEventFilter(self)

    # ----- building -----
    def _build(self, tools, bottom):
        self.root = QWidget()
        self.root.setObjectName("root")
        v = QVBoxLayout(self.root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.titlebar = TitleBar(self)
        self.titlebar.setVisible(sys.platform != "win32" or self.native_frame)
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
        else:
            self.show_page(key)

    def show_page(self, key):
        if key not in self.pages:
            return
        if key != self.current_key:
            self._previous_key = self.current_key
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
    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self.titlebar.refresh_icons()
        super().changeEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.titlebar.setVisible(True)
        else:
            self.titlebar.setVisible(False)  # full screen hides the strip
            self.showFullScreen()

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
        self.rail.setVisible(not settings.load().get("rail_hidden", False))

    def eventFilter(self, obj, event):
        if obj is self.content_host and event.type() == QEvent.Resize and self.drawer.isVisible():
            self._place_drawer()
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            return self._key(event)
        return False

    def closeEvent(self, event):
        if self.queue.busy():
            if not dialogs.ask("Stop the running job and close?", f"{self.queue.current.title} is still running. "
                               "Work finished so far is kept.", "Stop and close", kind="danger"):
                event.ignore()
                return
            self.queue.stop()
        if not getattr(self, "reset_on_close", False):
            settings.save({"window": bytes(self.saveGeometry().toBase64()).decode()})
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
        if ctrl or (mods & Qt.AltModifier) or typing:
            return False
        in_list = isinstance(QApplication.focusWidget(), QAbstractItemView)
        letters = {Qt.Key_K: lambda: self.show_page("keys"), Qt.Key_S: lambda: self.show_page("settings"),
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

    # ----- Windows: own title bar, keeping resize, snap and shadow -----
    def showEvent(self, event):
        super().showEvent(event)
        if self.native_frame and not getattr(self, "_frame_ready", False):
            self._frame_ready = True
            try:
                _setup_native_frame(int(self.winId()))
            except Exception as exc:
                self.log(f"Couldn't set up the custom title bar ({exc}); using the standard one.")

    def nativeEvent(self, event_type, message):
        if not self.native_frame:
            return False, 0
        try:
            return _native_event(self, message)
        except Exception:
            return False, 0


# ----- Win32 helpers -----
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    GWL_STYLE = -16
    WS_CAPTION, WS_THICKFRAME, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_SYSMENU = (0x00C00000, 0x00040000, 0x00010000,
                                                                           0x00020000, 0x00080000)
    HTCLIENT, HTCAPTION = 1, 2
    HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17

    class MARGINS(ctypes.Structure):
        _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    def _setup_native_frame(hwnd):
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.restype = ctypes.c_long
        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
        user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE,
                              style | WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU)
        try:
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(MARGINS(0, 0, 1, 0)))
        except Exception:
            pass
        # Ask Windows to recalculate the frame now (SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE)
        user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)

    def _frame_thickness(window):
        user32 = ctypes.windll.user32
        dpi = window.devicePixelRatioF()
        return int(user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)), dpi  # SM_CXSIZEFRAME + PADDEDBORDER

    def _native_event(window, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if window.isMaximized():
                # A maximised window hangs over the screen edge by its frame; keep the content on screen.
                params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                border, _dpi = _frame_thickness(window)
                r = params.rgrc[0]
                r.left += border
                r.top += border
                r.right -= border
                r.bottom -= border
            return True, 0  # the whole window is client area: no system title bar
        if msg.message == WM_NCHITTEST:
            from PySide6.QtGui import QCursor
            pos = window.mapFromGlobal(QCursor.pos())
            x, y, w, h = pos.x(), pos.y(), window.width(), window.height()
            edge = 6
            if not window.isMaximized() and not window.isFullScreen():
                left, right, top, bottom = x < edge, x >= w - edge, y < edge, y >= h - edge
                if top and left:
                    return True, HTTOPLEFT
                if top and right:
                    return True, HTTOPRIGHT
                if bottom and left:
                    return True, HTBOTTOMLEFT
                if bottom and right:
                    return True, HTBOTTOMRIGHT
                if left:
                    return True, HTLEFT
                if right:
                    return True, HTRIGHT
                if top:
                    return True, HTTOP
                if bottom:
                    return True, HTBOTTOM
            bar = window.titlebar
            if bar.isVisible() and y < TITLE_H:
                local = bar.mapFrom(window, pos)
                if bar.is_drag_area(local):
                    return True, HTCAPTION
            return True, HTCLIENT
        return False, 0
else:
    def _setup_native_frame(hwnd):
        pass

    def _native_event(window, message):
        return False, 0

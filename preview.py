"""Playing videos inside the app: the Gallery player and silent hover previews on duplicate cards.

Only one video plays at a time anywhere in the app. The Gallery player remembers its volume and always starts
from the beginning. Hover previews are silent and are off in safe mode. If Qt's video support is missing, the
app shows still pictures instead."""
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

import icons
import settings
import theme
from widgets import button, label

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    AVAILABLE = True
except Exception:  # Qt Multimedia missing or broken on this PC
    AVAILABLE = False

SAFE_MODE = False
_playing = None  # the one player that may play


def _claim(player):
    """Stop whatever else is playing."""
    global _playing
    if _playing is not None and _playing is not player:
        try:
            _playing.stop()
        except RuntimeError:
            pass
    _playing = player


def _clock(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


class Player(QWidget):
    """A video with play/pause, a position bar and volume. Nothing is drawn over the picture."""

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.ok = AVAILABLE
        if not self.ok:
            v.addWidget(label("Videos can't play inside the app on this PC. Use Open to play it in your player.",
                              "empty", wrap=True), 1)
            return
        self.video = QVideoWidget()
        self.video.setObjectName("stage")
        v.addWidget(self.video, 1)
        self.player = None  # made the first time a video plays, so start-up never waits for audio devices
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_btn = button("", "ghost", icon=icons.icon("play", theme.TEXT, 16), tip="Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle)
        controls.addWidget(self.play_btn)
        self.pos = QSlider(Qt.Horizontal)
        controls.addWidget(self.pos, 1)
        self.time = label("0:00 / 0:00", "caption")
        controls.addWidget(self.time)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(80)
        self.vol.setValue(int(float(settings.load().get("volume", 0.6)) * 100))
        self.vol.setToolTip("Volume (remembered)")
        self.vol.valueChanged.connect(self._volume)
        controls.addWidget(self.vol)
        v.addLayout(controls)

    def _ensure(self):
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(self.vol.value() / 100)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.pos.sliderMoved.connect(self.player.setPosition)
            self.player.durationChanged.connect(lambda d: self.pos.setRange(0, int(d)))
            self.player.positionChanged.connect(self._position)
            self.player.playbackStateChanged.connect(self._state)

    def load(self, path, play=True):
        if not self.ok:
            return
        self._ensure()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.setPosition(0)  # always from the beginning
        if play:
            _claim(self)
            self.player.play()

    def toggle(self):
        if not self.ok:
            return
        self._ensure()
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            _claim(self)
            self.player.play()

    def stop(self):
        if self.ok and self.player is not None:
            self.player.stop()

    def _volume(self, value):
        if self.player is not None:
            self.audio.setVolume(value / 100)
        settings.save({"volume": round(value / 100, 2)})

    def _position(self, ms):
        if not self.pos.isSliderDown():
            self.pos.setValue(int(ms))
        self.time.setText(f"{_clock(ms)} / {_clock(self.player.duration())}")

    def _state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", theme.TEXT, 16))


class HoverPreview(QObject):
    """Plays a silent preview over a card's picture while the pointer rests on it (one at a time)."""

    def __init__(self):
        super().__init__()
        self.target = None
        self.path = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._start)
        self.video = None
        self.player = None

    def enabled(self):
        return AVAILABLE and not SAFE_MODE and settings.load().get("hover_previews", True)

    def watch(self, widget, path):
        """Preview path over widget (a thumbnail label) when hovered."""
        widget.setProperty("preview_path", str(path))
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter and self.enabled():
            self.target = obj
            self.path = obj.property("preview_path")
            self.timer.start()
        elif event.type() == QEvent.Leave and obj is self.target:
            self.stop()
        return False

    def _start(self):
        if self.target is None:
            return
        try:
            if self.video is None:
                self.video = QVideoWidget()
                self.video.setAttribute(Qt.WA_TransparentForMouseEvents)
                self.player = QMediaPlayer(self)
                self.player.setVideoOutput(self.video)  # no audio output: silent
                self.player.setLoops(QMediaPlayer.Infinite)
            self.video.setParent(self.target)
            self.video.setGeometry(self.target.rect())
            self.video.show()
            self.player.setSource(QUrl.fromLocalFile(self.path))
            _claim(self)
            self.player.play()
        except RuntimeError:
            self.stop()

    def stop(self):
        self.timer.stop()
        self.target = None
        if self.player is not None:
            self.player.stop()
        if self.video is not None:
            try:
                self.video.hide()
                self.video.setParent(None)
            except RuntimeError:
                self.video = None


_hover = None


def hover():
    global _hover
    if _hover is None:
        _hover = HoverPreview()
    return _hover

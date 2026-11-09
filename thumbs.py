"""Thumbnails for lists, grids and cards, made in the background and kept in the Thumbnails place.

A thumbnail is a JPG up to 480 px, named after the file's path, size and date, so a changed file gets a new
one. Videos use a frame one second in (or the first frame); images are scaled with Pillow."""
import hashlib
import os
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

import paths
from media_utils import IMAGE_EXTENSIONS

MAX = 480


def _key(path):
    try:
        st = os.stat(path)
        raw = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        raw = os.path.normcase(os.path.abspath(path))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_file(path):
    key = _key(path)
    return paths.BY_KEY["thumbs"].path() / key[:2] / f"{key}.jpg"


def make(path):
    """Make (or find) the thumbnail file for path. Returns its path, or None if it can't be made."""
    target = cache_file(path)
    if target.exists():
        return target
    if paths.BY_KEY["thumbs"].missing():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{threading.get_ident()}.tmp")
    try:
        if Path(path).suffix.lower() in IMAGE_EXTENSIONS:
            from PIL import Image
            with Image.open(path) as img:
                img.thumbnail((MAX, MAX))
                img.convert("RGB").save(tmp, "JPEG", quality=82)
        else:
            from gif_maker import extract_frame
            img = extract_frame(path, 1.0, MAX) or extract_frame(path, 0.0, MAX)
            if img is None:
                return None
            img.convert("RGB").save(tmp, "JPEG", quality=82)
        os.replace(tmp, target)
        return target
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None


class _Task(QRunnable):
    def __init__(self, owner, path):
        super().__init__()
        self.owner, self.path = owner, path

    def run(self):
        image = None
        try:
            made = make(self.path)
            if made:
                image = QImage(str(made))
        except Exception:
            image = None
        self.owner._done(self.path, image)


class Thumbs(QObject):
    """get(path) returns a QImage at once if it's ready; otherwise it starts making one and emits ready(path)."""
    ready = Signal(str)
    _finished = Signal(str, object)

    def __init__(self, keep=800):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.memory = OrderedDict()
        self.keep = keep
        self.pending = set()
        self.failed = set()
        self._finished.connect(self._store)

    def get(self, path):
        image = self.memory.get(path)
        if image is not None:
            self.memory.move_to_end(path)
            return image
        if path not in self.pending and path not in self.failed:
            self.pending.add(path)
            self.pool.start(_Task(self, path))
        return None

    def failed_for(self, path):
        return path in self.failed

    def _done(self, path, image):
        self._finished.emit(path, image)  # back to the UI thread

    def _store(self, path, image):
        self.pending.discard(path)
        if image is None or image.isNull():
            self.failed.add(path)
        else:
            self.memory[path] = image
            while len(self.memory) > self.keep:
                self.memory.popitem(last=False)
        self.ready.emit(path)

    def forget(self):
        self.memory.clear()
        self.failed.clear()


_shared = None


def shared():
    global _shared
    if _shared is None:
        _shared = Thumbs()
    return _shared

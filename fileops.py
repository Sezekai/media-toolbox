"""File rules shared by every tool (STANDARDS.md, section 2).

- Nothing is permanently deleted: removals go to the Recycle Bin, and if it can't take a file we stop.
- Nothing is overwritten: a taken name gets " (2)", " (3)"...
"""
import json
import os
import shutil
from pathlib import Path


class RecycleError(Exception):
    """The Recycle Bin couldn't take a file. The file is left where it was."""


def unique_path(folder, name):
    """folder/name, or folder/'name (2).ext', 'name (3).ext'... when that name is taken."""
    folder = Path(folder)
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while True:
        target = folder / f"{stem} ({n}){suffix}"
        if not target.exists():
            return target
        n += 1


def recycle(path):
    """Send one file or folder to the Recycle Bin. Never falls back to a permanent delete."""
    from send2trash import send2trash
    try:
        send2trash(str(path))
    except Exception as exc:  # send2trash raises different errors per platform
        raise RecycleError(f"The Recycle Bin couldn't take {Path(path).name} ({exc}). It was left where it is.") from exc


def move_file(src, folder, name=None):
    """Move src into folder without replacing anything. Returns the new path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, name or Path(src).name)
    shutil.move(str(src), str(target))
    return target


def copy_file(src, folder, name=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, name or Path(src).name)
    shutil.copy2(str(src), str(target))
    return target


def write_json(path, data):
    """Write a temporary file, then rename it over the old one, so a crash never leaves half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def human_size(n):
    """1.2 GB, 640 KB, 12 bytes."""
    n = float(n or 0)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(n)} bytes"
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1024


def clock(seconds):
    """3:07, 12:31 or 1:04:09."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

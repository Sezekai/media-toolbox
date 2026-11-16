"""Shared helpers: finding files and running FFmpeg.

FFmpeg is bundled inside the .exe. From source, the copy in the FFmpeg storage place is used, then PATH.
Every FFmpeg run is registered with the running job, so Stop ends it at once."""
import os
import subprocess
import sys
from pathlib import Path

import jobs

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# Hide the console window that would otherwise flash up for each FFmpeg call on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
EXE = ".exe" if sys.platform == "win32" else ""


def noop(*_args, **_kwargs):
    """Stand-in for an optional progress or log callback."""


def tool_path(name):
    """The bundled binary, else the copy in the FFmpeg place, else the name (found on PATH)."""
    base = getattr(sys, "_MEIPASS", None)  # set by PyInstaller when running as an .exe
    if base and (Path(base) / (name + EXE)).exists():
        return str(Path(base) / (name + EXE))
    try:
        import paths
        candidate = paths.BY_KEY["ffmpeg"].path() / (name + EXE)
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass
    return name


def run(cmd, binary=False):
    """Run ffmpeg/ffprobe and wait. With binary=True, stdout is bytes (for image output).
    Text output is decoded as UTF-8; unreadable characters are replaced rather than raising."""
    cmd = [tool_path(cmd[0])] + [str(c) for c in cmd[1:]]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
    jobs.register_process(proc)
    out, err = proc.communicate()
    jobs.check_stop()
    if not binary:
        out = out.decode("utf-8", errors="replace")
        err = err.decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def probe_duration(path):
    return probe_video(path).get("duration")


def probe_video(path):
    """{"duration", "fps", "width", "height"} of a video; any value it cannot read is None."""
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
                  "-of", "default=noprint_wrappers=1", str(path)])
    values = {}
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition("=")
        values.setdefault(key.strip(), value.strip())

    def number(text):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def rate(text):
        num, _, den = (text or "").partition("/")
        num, den = number(num), number(den or "1")
        return num / den if num and den else None

    width, height = number(values.get("width")), number(values.get("height"))
    return {
        "duration": number(values.get("duration")),
        "fps": rate(values.get("avg_frame_rate")) or rate(values.get("r_frame_rate")),
        "width": int(width) if width else None,
        "height": int(height) if height else None,
    }


def find_files(folder, recursive, extensions):
    """Files with one of the extensions, sorted. Unreadable folders are skipped, not fatal. A file (dropped on
    a tool on its own) is itself, when it's the right kind."""
    folder = Path(folder)
    if folder.is_file():
        return [folder] if folder.suffix.lower() in extensions else []
    found = []
    if recursive:
        for dirpath, dirs, files in os.walk(folder, onerror=lambda e: None):
            dirs.sort()
            for name in files:
                if Path(name).suffix.lower() in extensions:
                    found.append(Path(dirpath) / name)
    else:
        try:
            found = [e for e in folder.iterdir() if e.is_file() and e.suffix.lower() in extensions]
        except OSError:
            found = []
    return sorted(found, key=lambda p: str(p).lower())


def find_videos(folder, recursive):
    return find_files(folder, recursive, VIDEO_EXTENSIONS)


def open_path(path):
    """Open a file with its default app."""
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - opening the user's own file
    else:
        subprocess.Popen(["xdg-open", str(path)])


def show_in_explorer(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(Path(path))])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])

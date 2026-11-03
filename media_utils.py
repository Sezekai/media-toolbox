"""Shared helpers: finding videos and running FFmpeg (bundled inside the .exe, or taken from PATH)."""
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}

# Hide the console window that would otherwise flash up for each FFmpeg call on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def noop(*_args, **_kwargs):
    """Stand-in for an optional progress or log callback."""


def _tool(name):
    """Use the binary bundled inside the .exe if present, otherwise the one on PATH."""
    base = getattr(sys, "_MEIPASS", None)  # set by PyInstaller when running as an .exe
    if base:
        candidate = Path(base) / (name + (".exe" if sys.platform == "win32" else ""))
        if candidate.exists():
            return str(candidate)
    return name


def run(cmd, binary=False):
    """Run ffmpeg/ffprobe. With binary=True, stdout is bytes (for image output).
    Text output is decoded as UTF-8, and any unreadable characters are replaced rather than raising."""
    cmd = [_tool(cmd[0])] + cmd[1:]
    if binary:
        return subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW)


def probe_duration(path):
    """Length of the video in seconds, or None if it can't be read."""
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "csv=p=0", str(path)])
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def probe_video(path):
    """{"duration", "fps", "width", "height"} of a video; any value it cannot read is None."""
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
                  "-of", "default=noprint_wrappers=1", str(path)])
    values = {}
    for line in result.stdout.splitlines():
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


def find_videos(folder, recursive):
    folder = Path(folder)
    iterator = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in iterator if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)

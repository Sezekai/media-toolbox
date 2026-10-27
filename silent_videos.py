"""Find videos with no audio, and move them to another folder.

Requires ffprobe and ffmpeg (from FFmpeg) on PATH.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}

# Hide the console window that would otherwise flash up for each FFmpeg call on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _tool(name):
    """Use the FFmpeg binary bundled inside the .exe if present, otherwise the one on PATH."""
    base = getattr(sys, "_MEIPASS", None)  # set by PyInstaller when running as an .exe
    if base:
        candidate = Path(base) / (name + (".exe" if sys.platform == "win32" else ""))
        if candidate.exists():
            return str(candidate)
    return name


def _run(cmd):
    cmd = [_tool(cmd[0])] + cmd[1:]
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)


def has_audio_stream(path):
    """True if the file contains at least one audio stream."""
    result = _run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
    ])
    return bool(result.stdout.strip())


def max_volume_db(path):
    """Peak volume of the first audio stream in dB, or None if it can't be measured."""
    result = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-",
    ])
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    return float(match.group(1)) if match else None


def find_videos(folder, recursive):
    folder = Path(folder)
    iterator = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in iterator if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)


def scan_folder(folder, recursive, check_loudness, threshold_db, log=print):
    """Return a list of (Path, reason) for videos that look silent."""
    videos = find_videos(folder, recursive)
    log(f"Checking {len(videos)} video(s)...")
    silent = []
    for i, path in enumerate(videos, 1):
        if not has_audio_stream(path):
            silent.append((path, "no audio track"))
            log(f"[{i}/{len(videos)}] no audio track: {path}")
            continue
        if check_loudness:
            peak = max_volume_db(path)
            if peak is None:
                log(f"[{i}/{len(videos)}] could not measure audio: {path}")
            elif peak <= threshold_db:
                silent.append((path, f"audio silent (peak {peak:.1f} dB)"))
                log(f"[{i}/{len(videos)}] silent audio: {path}")
    log(f"Done. {len(silent)} silent video(s) found.")
    return silent


def move_files(paths, dest, log=print):
    """Move files into dest. Returns the list of original paths that were moved."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for src in paths:
        target = dest / src.name
        counter = 1
        while target.exists():  # avoid overwriting a file with the same name
            target = dest / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        try:
            shutil.move(str(src), str(target))
            moved.append(src)
            log(f"Moved: {src.name}")
        except OSError as exc:
            log(f"Could not move {src}: {exc}")
    log(f"Moved {len(moved)} of {len(paths)} file(s) to {dest}")
    return moved

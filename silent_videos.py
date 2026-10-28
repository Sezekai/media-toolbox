"""Find videos with no audio, and move them to another folder."""
import re
import shutil
from pathlib import Path

from media_utils import find_videos, noop, run


def has_audio_stream(path):
    """True if the file contains at least one audio stream."""
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
    ])
    return bool(result.stdout.strip())


def max_volume_db(path):
    """Peak volume of the first audio stream in dB, or None if it can't be measured."""
    result = run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-",
    ])
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    return float(match.group(1)) if match else None


def scan_folder(folder, recursive, check_loudness, threshold_db, log=print, progress=None):
    """Return a list of (Path, reason) for videos that look silent."""
    progress = progress or noop
    videos = find_videos(folder, recursive)
    total = len(videos)
    log(f"Checking {total} video(s)...")
    silent = []
    for i, path in enumerate(videos, 1):
        progress(i - 1, total, "Checking")
        if not has_audio_stream(path):
            silent.append((path, "no audio track"))
            log(f"[{i}/{total}] no audio track: {path.name}")
        elif check_loudness:
            peak = max_volume_db(path)
            if peak is None:
                log(f"[{i}/{total}] could not measure audio: {path.name}")
            elif peak <= threshold_db:
                silent.append((path, f"audio silent (peak {peak:.1f} dB)"))
                log(f"[{i}/{total}] silent audio ({peak:.1f} dB): {path.name}")
    progress(total, total, "Checked")
    log(f"Done. {len(silent)} silent video(s) found.")
    return silent


def move_files(paths, dest, log=print, progress=None):
    """Move files into dest. Returns the list of original paths that were moved."""
    progress = progress or noop
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    total = len(paths)
    moved = []
    for i, src in enumerate(paths, 1):
        progress(i - 1, total, "Moving")
        target = dest / src.name
        counter = 1
        while target.exists():  # avoid overwriting a file with the same name
            target = dest / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        try:
            shutil.move(str(src), str(target))
            moved.append(src)
            log(f"[{i}/{total}] moved: {src.name}")
        except OSError as exc:
            log(f"[{i}/{total}] could not move {src.name}: {exc}")
    progress(total, total, "Moved")
    log(f"Moved {len(moved)} of {total} file(s) to {dest}")
    return moved

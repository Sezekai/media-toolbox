"""Find videos with no audio, and move them to another folder."""
import re
import shutil
from pathlib import Path

from media_utils import find_videos, run


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

"""Find videos with no sound, and move them to another folder."""
import re
from pathlib import Path

import fileops
import movelog
from media_utils import find_videos, noop, run


def has_audio_stream(path):
    """True if the file contains at least one audio stream."""
    result = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                  "-of", "csv=p=0", str(path)])
    return bool((result.stdout or "").strip())


def max_volume_db(path):
    """Peak volume of the first audio stream in dB, or None if it can't be measured."""
    result = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect",
                  "-f", "null", "-"])
    # A completely silent track reports "-inf dB", which counts as silent.
    match = re.search(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB", result.stderr or "")
    return float(match.group(1)) if match else None


def check_video(path, check_loudness, threshold_db):
    """(silent, reason) for one video. Raises if it can't be read."""
    if not has_audio_stream(path):
        return True, "No audio track"
    if check_loudness:
        peak = max_volume_db(path)
        if peak is None:
            return False, "Couldn't measure the sound"
        if peak <= threshold_db:
            return True, "Silent audio" if peak == float("-inf") else f"Very quiet ({peak:.1f} dB peak)"
    return False, "Has sound"


def scan(folders, recursive, check_loudness, threshold_db, log=print, progress=None, found=None):
    """Check every video in the folders. found(path, root, reason) is called for each silent one as soon as
    it's found. Returns [(path, root, reason)]."""
    progress = progress or noop
    videos = []
    for root in folders:
        progress(0, 0, f"Listing videos in {Path(root).name}")
        videos += [(p, root) for p in find_videos(root, recursive)]
    total = len(videos)
    log(f"Checking {total} video(s) in {len(folders)} folder(s)…")
    silent = []
    for i, (path, root) in enumerate(videos, 1):
        progress(i - 1, total, f"Checking {path.name}")
        try:
            is_silent, reason = check_video(path, check_loudness, threshold_db)
        except Exception as exc:  # one unreadable file shouldn't stop the whole scan
            if exc.__class__.__name__ == "JobStopped":
                raise
            log(f"[{i}/{total}] couldn't check {path.name}: {exc}")
            continue
        if is_silent:
            silent.append((path, root, reason))
            log(f"[{i}/{total}] {reason.lower()}: {path.name}")
            if found:
                found(path, root, reason)
    progress(total, total, "Checked")
    return silent


def move_videos(paths, dest, log=print, progress=None, done_one=None):
    """Move files into dest (a taken name gets " (2)"). Every move is written to the move log, so it can be
    undone. Returns [(src, dst)]."""
    progress = progress or noop
    dest = Path(dest)
    total = len(paths)
    moved, failed = [], 0
    try:
        for i, src in enumerate(paths, 1):
            progress(i - 1, total, f"Moving {Path(src).name}")
            try:
                target = fileops.move_file(src, dest)
                moved.append((str(src), str(target)))
                log(f"[{i}/{total}] moved {Path(src).name} → {target}")
                if done_one:
                    done_one(str(src), True)
            except OSError as exc:
                failed += 1
                log(f"[{i}/{total}] couldn't move {Path(src).name}: {exc}")
                if done_one:
                    done_one(str(src), False)
        progress(total, total, "Moved")
    finally:
        movelog.record("Silent videos", f"Moved {len(moved)} silent video(s) to {dest.name}",
                       [("move", s, d) for s, d in moved])
    return moved, failed

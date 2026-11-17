"""Make stills: two pictures from each video, for searching in Google Lens (the same as Lens Library's
Make stills, so its Import matches them back to the videos).

Each video gets "<video name> - start.jpg" (one second in, which is what its thumbnail usually shows) and
"<video name> - middle.jpg" (halfway through). A video that already has both is skipped."""
from pathlib import Path

from media_utils import noop, probe_video, run

KINDS = (("start", "Start"), ("middle", "Middle"))


def targets(video, out_dir):
    """{"start": path, "middle": path} for a video. out_dir None: beside the video."""
    folder = Path(out_dir) if out_dir else Path(video).parent
    stem = Path(video).stem
    return {k: folder / f"{stem} - {k}.jpg" for k, _label in KINDS}


def grab(video, seconds, out):
    result = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, seconds):.2f}", "-i", str(video), "-frames:v", "1",
                  "-q:v", "2", str(out)])
    if result.returncode != 0 or not Path(out).exists():
        lines = (result.stderr or "").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "FFmpeg couldn't read that frame")


def make(videos, out_dir, log=print, progress=None, state=None):
    """Make the stills for each video. state(path, "Working"/"Done"/"Skipped"/"Failed", detail).
    Returns (made, skipped, failed)."""
    progress = progress or noop
    state = state or noop
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    # Two videos with the same name would share stills in one folder, and Import couldn't tell them apart.
    seen = {}
    for v in videos:
        key = str(targets(v, out_dir)["start"]).lower()
        seen[key] = seen.get(key, 0) + 1
    total = len(videos)
    made = skipped = failed = 0
    for n, video in enumerate(videos, 1):
        name = Path(video).name
        progress(n - 1, total, f"Making stills of {name}")
        outs = targets(video, out_dir)
        if seen[str(outs["start"]).lower()] > 1:
            failed += 1
            msg = "another video with the same name goes into the same folder, so its stills would be mixed up"
            log(f"[{n}/{total}] {name}: {msg}")
            state(str(video), "Failed", msg)
            continue
        if all(p.exists() for p in outs.values()):
            skipped += 1
            state(str(video), "Skipped", "already has both stills")
            continue
        state(str(video), "Working", "")
        try:
            duration = probe_video(video).get("duration") or 0
            if not outs["start"].exists():
                grab(video, 1 if duration > 2 else 0, outs["start"])
            if not outs["middle"].exists():
                grab(video, duration / 2 if duration > 0 else 5, outs["middle"])
            made += 1
            log(f"[{n}/{total}] {name} → {outs['start'].name}, {outs['middle'].name}")
            state(str(video), "Done", f"{outs['start'].name} and {outs['middle'].name}")
        except Exception as exc:
            if exc.__class__.__name__ == "JobStopped":
                raise
            failed += 1
            log(f"[{n}/{total}] {name}: {exc}")
            state(str(video), "Failed", str(exc))
    progress(total, total, "Done")
    return made, skipped, failed

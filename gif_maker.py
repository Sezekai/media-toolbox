"""Turn video clips into animated GIFs with FFmpeg."""
import io
from pathlib import Path

from PIL import Image

import fileops
from media_utils import noop, run

# Quality presets: (palette stats mode, dither). Higher quality makes bigger files and takes longer.
QUALITY_PRESETS = {
    "Standard": ("diff", "bayer:bayer_scale=5"),
    "High": ("full", "bayer:bayer_scale=3"),
    "Maximum": ("full", "sierra2_4a"),
}


def extract_frame(path, seconds, max_width=320):
    """A single frame at the given time as a PIL image, or None if it can't be read."""
    result = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(seconds, 0):.3f}", "-i", str(path),
                  "-frames:v", "1", "-vf", f"scale='min({max_width},iw)':-2", "-f", "image2pipe", "-c:v", "png", "-"],
                 binary=True)
    if result.returncode != 0 or not result.stdout:
        return None
    img = Image.open(io.BytesIO(result.stdout))
    img.load()
    return img


def clean_name(name):
    """A file name without characters Windows doesn't allow, ending in .gif."""
    name = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip().rstrip(".")
    if not name:
        return ""
    return name if name.lower().endswith(".gif") else name + ".gif"


def output_path(src, out_dir, name=None):
    """<name>.gif beside the source (or in out_dir); a taken name gets " (2)"."""
    base = Path(out_dir) if out_dir else Path(src).parent
    return fileops.unique_path(base, clean_name(name or "") or Path(src).stem + ".gif")


def make_gif(src, dst, start, end, fps, width, quality="Standard"):
    """Convert src[start:end] to a GIF. end=None means until the end of the video."""
    stats, dither = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["Standard"])
    palette_filter = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
                      f"[a]palettegen=stats_mode={stats}[p];[b][p]paletteuse=dither={dither}")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    cmd += ["-filter_complex", palette_filter, "-loop", "0", str(dst)]
    result = run(cmd)
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "FFmpeg failed")


def convert_batch(jobs, quality, out_dir, log=print, progress=None, state=None):
    """jobs: [(source, start, end or None, fps, width, name or None)]. Every video has its own frame rate,
    width and name. state(path, "Working"/"Done"/"Failed", detail) reports each video. Returns (made, failed)."""
    progress = progress or noop
    state = state or noop
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    total = len(jobs)
    made, failed = 0, 0
    log(f"Quality: {quality}")
    for i, (src, start, end, fps, width, name) in enumerate(jobs, 1):
        src = Path(src)
        progress(i - 1, total, f"Converting {src.name}")
        state(str(src), "Working", "")
        dst = output_path(src, out_dir, name)
        span = "whole video" if end is None and start <= 0 else (
            f"{start:.2f}s to {end:.2f}s" if end is not None else f"from {start:.2f}s")
        log(f"[{i}/{total}] {src.name} ({span}, {fps:g} fps, {width} px) → {dst.name}")
        try:
            make_gif(src, dst, start, end, fps, width, quality)
            made += 1
            state(str(src), "Done", dst.name)
        except Exception as exc:  # keep going with the rest of the batch
            if exc.__class__.__name__ == "JobStopped":
                try:
                    if dst.exists():
                        dst.unlink()  # our own half-written GIF
                except OSError:
                    pass
                raise
            failed += 1
            log(f"  failed: {exc}")
            state(str(src), "Failed", str(exc))
    progress(total, total, "Converted")
    return made, failed

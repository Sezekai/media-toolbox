"""Turn video clips into animated GIFs with FFmpeg."""
import io
from pathlib import Path

from PIL import Image

from media_utils import noop, run

# Quality presets control the colour palette and dithering. Higher quality makes bigger files and takes longer.
# (palette stats mode, dither setting)
QUALITY_PRESETS = {
    "Standard": ("diff", "bayer:bayer_scale=5"),
    "High": ("full", "bayer:bayer_scale=3"),
    "Maximum": ("full", "sierra2_4a"),
}


def extract_frame(path, seconds, max_width=320):
    """A single frame at the given time as a PIL image, or None if it can't be read."""
    result = run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(seconds, 0):.3f}", "-i", str(path),
        "-frames:v", "1", "-vf", f"scale={max_width}:-2",
        "-f", "image2pipe", "-c:v", "png", "-",
    ], binary=True)
    if result.returncode != 0 or not result.stdout:
        return None
    img = Image.open(io.BytesIO(result.stdout))
    img.load()
    return img


def output_path(src, out_dir):
    """<name>.gif beside the source (or in out_dir), never overwriting an existing file."""
    base = Path(out_dir) if out_dir else Path(src).parent
    target = base / (Path(src).stem + ".gif")
    counter = 1
    while target.exists():
        target = base / f"{Path(src).stem} ({counter}).gif"
        counter += 1
    return target


def make_gif(src, dst, start, end, fps, width, quality="Standard"):
    """Convert src[start:end] to a GIF. end=None means until the end of the video."""
    stats, dither = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["Standard"])
    palette_filter = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
        f"[a]palettegen=stats_mode={stats}[p];[b][p]paletteuse=dither={dither}"
    )
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    cmd += ["-filter_complex", palette_filter, "-loop", "0", str(dst)]
    result = run(cmd)
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "ffmpeg failed")


def convert_batch(jobs, fps, width, quality, out_dir, log=print, progress=None):
    """jobs: list of (source Path, start seconds, end seconds or None for the whole video)."""
    progress = progress or noop
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    total = len(jobs)
    made = 0
    log(f"Quality: {quality}, {fps} fps, {width} px wide")
    for i, (src, start, end) in enumerate(jobs, 1):
        progress(i - 1, total, "Converting")
        dst = output_path(src, out_dir)
        if end is None and start <= 0:
            label = "whole video"
        else:
            label = f"{start:.2f}s to {end:.2f}s" if end is not None else f"from {start:.2f}s"
        log(f"[{i}/{total}] {src.name} ({label}) -> {dst.name}")
        try:
            make_gif(src, dst, start, end, fps, width, quality)
            made += 1
        except Exception as exc:  # keep going with the rest of the batch
            log(f"  failed: {exc}")
    progress(total, total, "Converted")
    log(f"Made {made} of {total} GIF(s).")

"""Convert .webp images to .jpg beside each original."""
from pathlib import Path

from PIL import Image

import fileops
from media_utils import find_files, noop


def find_webp(folder, recursive):
    return find_files(folder, recursive, {".webp"})


def to_jpg(src, dst, quality):
    with Image.open(src) as img:
        # JPG has no transparency, so transparent areas are filled with white.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
        # Metadata (EXIF, ICC profile) isn't copied, and only the first frame of an animated WebP is kept.
        img.save(dst, "JPEG", quality=quality, optimize=True)


def convert_files(files, quality, recycle_originals, log=print, progress=None, state=None):
    """Convert each file; a taken .jpg name gets " (2)". state(path, "Working"/"Done"/"Failed", detail) is
    called for each file. Returns (made, failed)."""
    progress = progress or noop
    state = state or noop
    files = [Path(f) for f in files]
    total = len(files)
    log(f"JPG quality {quality}%. Transparent areas become white. Metadata isn't kept.")
    made, failed = 0, 0
    for i, src in enumerate(files, 1):
        progress(i - 1, total, f"Converting {src.name}")
        state(str(src), "Working", "")
        dst = fileops.unique_path(src.parent, src.stem + ".jpg")
        try:
            to_jpg(src, dst, quality)
        except Exception as exc:
            failed += 1
            log(f"[{i}/{total}] failed: {src.name}: {exc}")
            state(str(src), "Failed", str(exc))
            continue
        made += 1
        log(f"[{i}/{total}] {src.name} → {dst.name}")
        detail = dst.name
        if recycle_originals:
            try:
                fileops.recycle(src)
                log(f"  sent the original to the Recycle Bin: {src.name}")
                detail += " · original in the Recycle Bin"
            except fileops.RecycleError as exc:
                log(f"  {exc}")
        state(str(src), "Done", detail)
    progress(total, total, "Converted")
    return made, failed

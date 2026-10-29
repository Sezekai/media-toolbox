"""Find .webp images and convert them to .jpg in the same folder as each original."""
from pathlib import Path

from PIL import Image
from send2trash import send2trash

from media_utils import noop


def find_webp(folder, recursive):
    """All .webp files in the folder (and subfolders if recursive), as sorted Paths."""
    folder = Path(folder)
    iterator = folder.rglob("*.webp") if recursive else folder.glob("*.webp")
    return sorted(p for p in iterator if p.is_file())


def _to_jpg(src, dst, quality):
    with Image.open(src) as img:
        # JPG has no transparency, so transparent areas are filled with white.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
        # Metadata (EXIF, ICC profile) is not copied, and only the first frame of an animated WebP is kept.
        img.save(dst, "JPEG", quality=quality, optimize=True)


def convert_files(files, quality, delete_originals, log=print, progress=None):
    progress = progress or noop
    files = [Path(f) for f in files]
    total = len(files)
    log(f"JPG quality {quality}%. Transparent areas become white. Metadata is not kept.")
    converted = 0
    for i, src in enumerate(files, 1):
        progress(i - 1, total, "Converting")
        dst = src.with_suffix(".jpg")
        if dst.exists():
            log(f"[{i}/{total}] skipped (JPG already exists): {dst.name}")
            continue
        try:
            _to_jpg(src, dst, quality)
        except Exception as exc:
            log(f"[{i}/{total}] failed: {src.name}: {exc}")
            continue
        converted += 1
        log(f"[{i}/{total}] converted: {src.name} -> {dst.name}")
        if delete_originals:
            try:
                send2trash(str(src))
                log(f"  sent original to Recycle Bin: {src.name}")
            except Exception as exc:
                log(f"  could not recycle {src.name}: {exc}")
    progress(total, total, "Converted")
    log(f"Converted {converted} of {total} file(s).")

"""Convert .webp images to .jpg in the same directory as each original."""
from pathlib import Path

from PIL import Image
from send2trash import send2trash

from media_utils import noop


def convert_webp_to_jpg(folder, recursive, delete_originals, log=print, progress=None):
    progress = progress or noop
    folder = Path(folder)
    files = sorted(folder.rglob("*.webp") if recursive else folder.glob("*.webp"))
    total = len(files)
    log(f"Found {total} .webp file(s).")
    converted = 0
    for i, src in enumerate(files, 1):
        progress(i - 1, total, "Converting")
        dst = src.with_suffix(".jpg")
        if dst.exists():
            log(f"[{i}/{total}] skipped (JPG already exists): {dst.name}")
            continue
        try:
            with Image.open(src) as img:
                # JPG has no transparency; flatten onto white.
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert("RGB")
                img.save(dst, "JPEG", quality=95)
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

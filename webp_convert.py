"""Convert .webp images to .jpg in the same directory as each original."""
from pathlib import Path

from PIL import Image
from send2trash import send2trash


def convert_webp_to_jpg(folder, recursive, delete_originals, log=print):
    folder = Path(folder)
    files = sorted(folder.rglob("*.webp") if recursive else folder.glob("*.webp"))
    log(f"Found {len(files)} .webp file(s).")
    converted = 0
    for src in files:
        dst = src.with_suffix(".jpg")
        if dst.exists():
            log(f"Skipped (JPG already exists): {dst}")
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
            log(f"Failed: {src.name}: {exc}")
            continue
        converted += 1
        log(f"Converted: {src.name} -> {dst.name}")
        if delete_originals:
            try:
                send2trash(str(src))
                log(f"Sent to Recycle Bin: {src.name}")
            except Exception as exc:
                log(f"Could not recycle {src.name}: {exc}")
    log(f"Converted {converted} of {len(files)} file(s).")

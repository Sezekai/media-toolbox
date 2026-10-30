"""Folder utilities: zip each subfolder, and copy a folder tree without files."""
import os
import zipfile
from pathlib import Path

from media_utils import noop


def zip_subfolders(src, dst=None, log=print, progress=None, only=None):
    """Zip the immediate subfolders of src into dst (default: src) as FolderName.zip.
    only: optional set of folder names to zip; the others are left out."""
    progress = progress or noop
    src = Path(src)
    dst = Path(dst) if dst else src
    dst.mkdir(parents=True, exist_ok=True)
    subfolders = sorted(p for p in src.iterdir() if p.is_dir() and (only is None or p.name in only))
    total = len(subfolders)
    log(f"Zipping {total} subfolder(s) into {dst}")
    for i, folder in enumerate(subfolders, 1):
        progress(i - 1, total, "Zipping")
        zip_path = dst / f"{folder.name}.zip"
        if zip_path.exists():
            log(f"[{i}/{total}] skipped (zip already exists): {zip_path.name}")
            continue
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(folder):
                    for name in files:
                        full = Path(root) / name
                        # Store paths relative to src so the zip contains FolderName/...
                        zf.write(full, full.relative_to(src))
            log(f"[{i}/{total}] zipped: {folder.name}")
        except Exception as exc:
            log(f"[{i}/{total}] failed {folder.name}: {exc}")
    progress(total, total, "Zipped")
    log("Zip finished.")


def copy_folder_structure(src, dst, log=print, progress=None, skip=None):
    """Recreate src's folder tree (no files) inside dst/<src name>.
    skip: optional set of folder paths relative to src (POSIX style) to leave out, with everything inside them."""
    src = Path(src)
    target_root = Path(dst) / src.name
    skip = skip or set()
    count = 0
    for root, dirs, _ in os.walk(src):
        rel = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if (rel / d).as_posix() not in skip]  # don't walk into skipped folders
        (target_root / rel).mkdir(parents=True, exist_ok=True)
        count += 1
        log(f"created: {rel}")
    log(f"Created {count} folder(s) at {target_root}")

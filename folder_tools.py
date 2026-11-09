"""Folder utilities: zip each subfolder, and copy a folder tree without its files."""
import os
import zipfile
from pathlib import Path

import fileops
from media_utils import noop


def zip_subfolders(src, dst=None, log=print, progress=None, only=None):
    """Zip the subfolders of src into dst (default: src) as FolderName.zip; a taken name gets " (2)".
    only: the folder names to zip. Returns (made, failed)."""
    progress = progress or noop
    src = Path(src)
    dst = Path(dst) if dst else src
    dst.mkdir(parents=True, exist_ok=True)
    subfolders = sorted(p for p in src.iterdir() if p.is_dir() and (only is None or p.name in only))
    total = len(subfolders)
    log(f"Zipping {total} folder(s) into {dst}")
    made, failed = 0, 0
    for i, folder in enumerate(subfolders, 1):
        progress(i - 1, total, f"Zipping {folder.name}")
        zip_path = fileops.unique_path(dst, f"{folder.name}.zip")
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(folder):
                    for name in files:
                        full = Path(root) / name
                        zf.write(full, full.relative_to(src))  # the zip holds FolderName/...
            made += 1
            log(f"[{i}/{total}] {folder.name} → {zip_path.name}")
        except Exception as exc:
            failed += 1
            log(f"[{i}/{total}] couldn't zip {folder.name}: {exc}")
            try:
                if zip_path.exists():
                    zip_path.unlink()  # our own half-written zip, not a user file
            except OSError:
                pass
    progress(total, total, "Zipped")
    return made, failed


def copy_folder_structure(src, dst, log=print, progress=None, skip=None):
    """Recreate src's folder tree (no files) inside dst/<src name> (" (2)" if taken).
    skip: folder paths relative to src (POSIX style) to leave out, with everything inside them."""
    progress = progress or noop
    src = Path(src)
    target_root = fileops.unique_path(Path(dst), src.name)
    skip = skip or set()
    walk = []
    for root, dirs, _files in os.walk(src):
        rel = Path(root).relative_to(src)
        dirs[:] = sorted(d for d in dirs if (rel / d).as_posix() not in skip)
        walk.append(rel)
    total = len(walk)
    for i, rel in enumerate(walk, 1):
        progress(i - 1, total, f"Creating {rel.as_posix() if str(rel) != '.' else src.name}")
        (target_root / rel).mkdir(parents=True, exist_ok=True)
    progress(total, total, "Created")
    log(f"Created {total} folder(s) at {target_root}")
    return total, target_root

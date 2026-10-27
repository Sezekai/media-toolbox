"""Folder utilities: zip each subfolder, and copy a folder tree without files."""
import os
import zipfile
from pathlib import Path


def zip_subfolders(src, dst=None, log=print):
    """Zip every immediate subfolder of src into dst (default: src) as FolderName.zip."""
    src = Path(src)
    dst = Path(dst) if dst else src
    dst.mkdir(parents=True, exist_ok=True)
    subfolders = sorted(p for p in src.iterdir() if p.is_dir())
    log(f"Zipping {len(subfolders)} subfolder(s) into {dst}")
    for folder in subfolders:
        zip_path = dst / f"{folder.name}.zip"
        if zip_path.exists():
            log(f"Skipped (zip already exists): {zip_path.name}")
            continue
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(folder):
                    for name in files:
                        full = Path(root) / name
                        # Store paths relative to src so the zip contains FolderName/...
                        zf.write(full, full.relative_to(src))
            log(f"Zipped: {folder.name}")
        except Exception as exc:
            log(f"Failed {folder.name}: {exc}")
    log("Zip finished.")


def copy_folder_structure(src, dst, log=print):
    """Recreate src's folder tree (no files) inside dst/<src name>."""
    src = Path(src)
    target_root = Path(dst) / src.name
    count = 0
    for root, dirs, _ in os.walk(src):
        rel = Path(root).relative_to(src)
        (target_root / rel).mkdir(parents=True, exist_ok=True)
        count += 1
    log(f"Created {count} folder(s) at {target_root}")

"""Updates from inside the app.

The app asks GitHub for the newest release, and after you say yes it downloads it (with full progress),
checks it, puts it in place of the running copy and restarts. A file the app downloads itself isn't marked as
"from the internet", so Windows doesn't stop it with a "Windows protected your PC" warning the way it does a
program downloaded in a browser."""
import json
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import fileops
import paths
import settings
from version import __version__

REPO = "Sezekai/media-toolbox"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE = "MediaToolbox.exe"


def _numbers(tag):
    out = []
    for part in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out + [0] * (3 - len(out)))


def frozen():
    return bool(getattr(sys, "frozen", False))


def latest(log=print, progress=None):
    """{"tag", "version", "newer", "name", "size", "url", "notes"} for the newest release."""
    if progress:
        progress(0, 0, "Asking GitHub for the newest version")
    req = urllib.request.Request(API, headers={"User-Agent": "MediaToolbox", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    tag = data.get("tag_name", "")
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith("-windows.zip")), None)
    asset = asset or next((a for a in data.get("assets", []) if a.get("name", "") == EXE), None)
    info = {"tag": tag, "version": tag.lstrip("vV"), "newer": _numbers(tag) > _numbers(__version__),
            "name": asset["name"] if asset else "", "size": int(asset.get("size") or 0) if asset else 0,
            "url": asset["browser_download_url"] if asset else "", "notes": (data.get("body") or "").strip()}
    settings.save({"last_update_check": time.time()})
    log(f"Newest version: {info['version'] or 'unknown'} (this is {__version__}).")
    return info


def due():
    """True when the daily check should run."""
    s = settings.load()
    return s.get("check_updates", True) and time.time() - float(s.get("last_update_check", 0)) > 20 * 3600


def install(info, log, progress):
    """Download the release, check it, and put the new MediaToolbox.exe in place of this one. The running copy
    is renamed MediaToolbox.old.exe (Windows lets a running program be renamed) and removed next start."""
    from duplicates_engine import download  # the shared downloader: bytes, MB/s, a .part file first
    if not frozen():
        raise RuntimeError("this copy runs from source, so update it with git pull instead")
    exe = Path(sys.executable)
    work = Path(tempfile.mkdtemp(prefix="update-", dir=paths.place("temp")))
    new = exe.with_name("MediaToolbox.new.exe")
    try:
        target = work / info["name"]
        download(info["url"], target, log, progress, f"Media Toolbox {info['version']}")
        progress(0, 0, "Checking the download")
        if target.suffix.lower() == ".zip":
            with zipfile.ZipFile(target) as z:
                bad = z.testzip()
                if bad:
                    raise RuntimeError(f"the download is damaged ({bad}); nothing was changed")
                member = next((m for m in z.namelist() if m.replace("\\", "/").split("/")[-1] == EXE), None)
                if not member:
                    raise RuntimeError(f"{EXE} wasn't in the download; nothing was changed")
                with z.open(member) as src, open(new, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
        else:
            os.replace(target, new)
        if new.stat().st_size < 1024 * 1024:
            raise RuntimeError("the new program is too small to be right; nothing was changed")
        old = exe.with_name("MediaToolbox.old.exe")
        if old.exists():
            old.unlink()  # the app's own leftover from the last update
        os.replace(exe, old)
        try:
            os.replace(new, exe)
        except OSError:
            os.replace(old, exe)  # put the running copy back
            raise
        log(f"Media Toolbox {info['version']} is in place. It starts the next time the app opens.")
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)  # the app's own temporary folder
        if new.exists():
            try:
                new.unlink()
            except OSError:
                pass
    return {"summary": f"Media Toolbox {info['version']} installed", "version": info["version"]}


def clean_up():
    """Remove the copy an earlier update left behind (it can't be removed while it's still running)."""
    if frozen():
        old = Path(sys.executable).with_name("MediaToolbox.old.exe")
        try:
            if old.exists():
                old.unlink()  # the app's own file
        except OSError:
            pass


def size_text(info):
    return fileops.human_size(info["size"]) if info.get("size") else "size not known"

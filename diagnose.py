"""Diagnose, Repair and Copy report (STANDARDS.md, "Self-checks").

Each finding has a kind (ok, warn, error), a title, the evidence that led to it and, when something is
wrong, what fixes it. Repair only touches the app's own files: temporary files, missing folders, the FFmpeg
copy for the engine. The report is copied to the clipboard and saved in the logs folder."""
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import duplicates_engine as de
import fileops
import gpu
import logs
import paths
import settings
import version
from media_utils import tool_path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _finding(kind, title, evidence, fix=""):
    return {"kind": kind, "title": title, "evidence": evidence, "fix": fix}


def _runs(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW,
                             encoding="utf-8", errors="replace")
        return out.returncode == 0, (out.stdout or out.stderr or "").strip().splitlines()[:1]
    except (OSError, subprocess.SubprocessError) as exc:
        return False, [str(exc)]


def run(log=print, progress=None):
    """Every check, in order. Returns the findings."""
    steps = ["places", "ffmpeg", "engine", "gpu", "disk", "leftovers", "crashes"]
    found = []

    def step(n, text):
        if progress:
            progress(n, len(steps), text)

    step(0, "Checking the storage places")
    for place in paths.PLACES:
        path = place.path()
        if place.missing():
            found.append(_finding("error", f"{place.title}: the drive isn't there", str(path),
                                  "Plug the drive back in, or choose a new place in Settings › Storage."))
            continue
        try:
            paths.ensure(path)
            probe = path / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            found.append(_finding("ok", f"{place.title}", str(path)))
        except OSError as exc:
            found.append(_finding("error", f"{place.title}: can't write there", f"{path}: {exc}",
                                  "Choose a folder you can write to in Settings › Storage."))

    step(1, "Checking FFmpeg")
    exe = tool_path("ffmpeg")
    ok, first = _runs([exe, "-hide_banner", "-version"])
    if ok:
        found.append(_finding("ok", "FFmpeg works", f"{exe}: {first[0] if first else ''}"))
    else:
        found.append(_finding("error", "FFmpeg doesn't run", f"{exe}: {first[0] if first else 'no output'}",
                              "Repair copies the bundled FFmpeg again. From source, install FFmpeg on PATH."))
    ready, text = de.ffmpeg_ready()
    if not ready:
        found.append(_finding("warn", "The duplicate engine can't find FFmpeg", text,
                              "Repair copies the bundled FFmpeg into the FFmpeg place."))

    step(2, "Checking the duplicate engine")
    engine = de.find_engine()
    if not engine:
        found.append(_finding("warn", "The duplicate engine isn't installed", str(paths.BY_KEY["engine"].path()),
                              "Settings › Duplicate engine › Install engine."))
    else:
        ok, first = _runs([engine, "--version"])
        if ok:
            found.append(_finding("ok", f"Duplicate engine {de.installed_version() or ''} runs".replace("  ", " "),
                                  f"{engine}: {first[0] if first else ''}"))
        else:
            hint = " (WinError 216 means it was built for another processor)" if "216" in " ".join(first) else ""
            found.append(_finding("error", "The duplicate engine doesn't start", f"{engine}: "
                                  f"{first[0] if first else 'no output'}{hint}",
                                  "Install the engine again from Settings › Duplicate engine."))

    step(3, "Checking the GPU")
    card = gpu.detect()
    use, reason = gpu.use_gpu()
    if card:
        found.append(_finding("ok", f"GPU: {card['name']}", f"Driver {card['driver']}, "
                              f"{card['memory_mb'] / 1024:.1f} GB. {reason}"))
    elif gpu.mode() == "gpu":
        found.append(_finding("warn", "Settings ask for the GPU, but no NVIDIA GPU was found", reason,
                              "Install the NVIDIA driver, or set Use to Auto or CPU."))
    else:
        found.append(_finding("ok", "No NVIDIA GPU, so the CPU is used", reason))

    step(4, "Checking free space")
    try:
        free = shutil.disk_usage(paths.root().anchor or str(paths.root())).free
        kind = "warn" if free < 2 * 1024 ** 3 else "ok"
        found.append(_finding(kind, f"{fileops.human_size(free)} free on the app's drive", str(paths.root()),
                              "Free up space, or move Fingerprints and Cache to another drive in Settings › "
                              "Storage." if kind == "warn" else ""))
    except OSError:
        pass

    step(5, "Looking for leftovers")
    temp = paths.BY_KEY["temp"].path()
    if temp.exists():
        size, count = paths.folder_size(temp)
        if count:
            found.append(_finding("warn", f"{count} leftover temporary file(s)", f"{temp} ({fileops.human_size(size)})",
                                  "Repair empties the temporary folder (nothing of yours is in it)."))
    parts = list(paths.BY_KEY["engine"].path().glob("**/*.part")) if paths.BY_KEY["engine"].path().exists() else []
    if parts:
        found.append(_finding("warn", "An unfinished download was left behind", str(parts[0]),
                              "Repair removes it; install again to download it fully."))

    step(6, "Looking for crash logs")
    crashes = sorted(paths.logs_dir().glob("crash-*.txt"))
    if crashes:
        found.append(_finding("warn", f"{len(crashes)} crash log(s)", str(crashes[-1]),
                              "Copy report and send it with the newest crash log when reporting the problem."))
    else:
        found.append(_finding("ok", "No crash logs", str(paths.logs_dir())))
    if progress:
        progress(len(steps), len(steps), "Done")
    return found


def repair(log=print, progress=None):
    """Fix what can be fixed safely. Returns a list of what was done."""
    done = []
    for place in paths.PLACES:
        if not place.missing() and not place.path().exists():
            paths.ensure(place.path())
            done.append(f"Made the missing folder {place.path()}")
    temp = paths.BY_KEY["temp"].path()
    if temp.exists():
        for child in temp.iterdir():
            try:
                shutil.rmtree(child) if child.is_dir() else child.unlink()  # the app's own temporary files
            except OSError as exc:
                log(f"Couldn't remove {child}: {exc}")
        done.append(f"Emptied {temp}")
    engine_dir = paths.BY_KEY["engine"].path()
    for part in (engine_dir.glob("**/*.part") if engine_dir.exists() else []):
        try:
            part.unlink()
            done.append(f"Removed the unfinished download {part.name}")
        except OSError:
            pass
    ffmpeg_dir = paths.BY_KEY["ffmpeg"].path()
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for name in ("ffmpeg", "ffprobe"):
            exe = name + (".exe" if sys.platform == "win32" else "")
            src = Path(base) / exe
            if src.exists():
                paths.ensure(ffmpeg_dir)
                shutil.copy2(src, ffmpeg_dir / exe)
        done.append(f"Copied the bundled FFmpeg into {ffmpeg_dir}")
    logs.end_session()
    done.append("Cleared the record of unclean exits (safe mode starts fresh)")
    for line in done:
        log(f"Repair: {line}")
    return done


def report(findings):
    lines = [f"Media Toolbox {version.__version__} · {time.strftime('%Y-%m-%d %H:%M')}",
             f"Python {platform.python_version()} · {platform.platform()}", ""]
    for f in findings:
        mark = {"ok": "OK  ", "warn": "WARN", "error": "FAIL"}[f["kind"]]
        lines.append(f"[{mark}] {f['title']}")
        lines.append(f"       {f['evidence']}")
        if f["fix"]:
            lines.append(f"       Fix: {f['fix']}")
    lines += ["", "Places:"] + [f"  {p.title}: {p.path()}" for p in paths.PLACES]
    lines += ["", "Settings keys: " + ", ".join(sorted(settings.load().keys())), "", "Last log lines:"]
    lines += logs.recent_lines()[-40:]
    text = "\n".join(lines)
    try:
        (paths.logs_dir() / time.strftime("diagnose-%Y%m%d-%H%M%S.txt")).write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text

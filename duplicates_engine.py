"""Duplicate video detection. Wraps the vdf-cli engine from 0x90d/videoduplicatefinder (AGPLv3).

The engine is NOT bundled with this app. It is downloaded at runtime into the app data folder, and
FFmpeg is copied from the bundled copy or downloaded the same way the build does. Nothing here
permanently deletes a file: removals go to the Recycle Bin and are logged to a CSV file."""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import settings

REPO = "0x90d/videoduplicatefinder"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
ENGINE_NAME = "vdf-cli.exe" if sys.platform == "win32" else "vdf-cli"
PROGRESS_RE = re.compile(r"\[\s*(\d{1,3})%\]")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
MATCH_LABELS = {
    "exact": "Exact",
    "near": "Near",
    "partial_audio": "Partial clip (audio)",
    "partial_visual": "Partial clip (visual AI)",
}


# ---------- folders and install state ----------
def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = Path(base) / "Media Toolbox" / "duplicates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def engine_dir():
    folder = data_dir() / "engine"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def find_engine():
    """The installed vdf-cli, or None."""
    saved = settings.load().get("dup_engine_path")
    if saved and Path(saved).exists():
        return saved
    found = list(engine_dir().rglob(ENGINE_NAME))
    return str(found[0]) if found else None


def installed_version():
    return settings.load().get("dup_engine_version", "")


def ffmpeg_ready():
    """FFmpeg and FFprobe must be on PATH or beside the engine. Returns (ok, message)."""
    folder = engine_dir()
    missing = []
    for name in ("ffmpeg", "ffprobe"):
        exe = name + (".exe" if sys.platform == "win32" else "")
        if not (folder / exe).exists() and not shutil.which(name):
            missing.append(name)
    if missing:
        return False, "Missing " + " and ".join(missing)
    return True, "Found"


def _copy_bundled_ffmpeg(log):
    """The .exe ships with ffmpeg and ffprobe. Copy them beside the engine so the CLI can find them."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return False
    copied = False
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        src = Path(base) / name
        if src.exists() and not (engine_dir() / name).exists():
            shutil.copy2(src, engine_dir() / name)
            copied = True
    if copied:
        log("Copied the FFmpeg bundled with this app next to the engine.")
    return copied


# ---------- downloads ----------
def _download(url, dest, log, progress, label):
    request = urllib.request.Request(url, headers={"User-Agent": "MediaToolbox"})
    with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                progress(done, total, f"Downloading {label}")
    log(f"Downloaded {label} ({done // (1024 * 1024)} MB).")


def latest_release():
    """Tag name and asset list of the newest engine release. Asset names are listed in errors,
    so nothing is guessed silently."""
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": "MediaToolbox",
                                                            "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    return data.get("tag_name", ""), data.get("assets", [])


def _pc_architecture():
    """'arm64' or 'x64' for this PC, from the Windows environment."""
    raw = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    return "arm64" if "ARM64" in raw else "x64"


def pick_cli_asset(assets):
    """The Windows CLI zip for this PC's processor (x64 or arm64). Running an arm64 build on an x64 PC
    fails with WinError 216, so the architecture must match."""
    arch = _pc_architecture()
    other = "x64" if arch == "arm64" else "arm64"
    candidates = []
    for asset in assets:
        name = asset.get("name", "").lower()
        if name.endswith(".zip") and "cli" in name and "win" in name:
            candidates.append((asset, name))
    for asset, name in candidates:
        if arch in name:
            return asset
    for asset, name in candidates:
        if other not in name:
            return asset  # a build with no architecture in its name
    names = ", ".join(a.get("name", "?") for a in assets) or "none"
    raise RuntimeError(f"No Windows CLI zip for {arch} in the latest release. Assets: {names}")


def check_update():
    """(installed, latest). installed is '' when the engine is not installed."""
    tag, _ = latest_release()
    return installed_version(), tag


def install_engine(log, progress):
    tag, assets = latest_release()
    asset = pick_cli_asset(assets)
    log(f"Latest engine release: {tag}. Downloading {asset['name']}.")
    work = Path(tempfile.mkdtemp(prefix="vdf-", dir=data_dir()))
    try:
        zip_path = work / "engine.zip"
        _download(asset["browser_download_url"], zip_path, log, progress, "engine")
        progress(1, 1, "Extracting engine")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(engine_dir())
        found = list(engine_dir().rglob(ENGINE_NAME))
        if not found:
            raise RuntimeError(f"{ENGINE_NAME} was not in the downloaded zip")
        settings.save({"dup_engine_path": str(found[0]), "dup_engine_version": tag})
        log(f"Engine {tag} installed.")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _copy_bundled_ffmpeg(log)


def install_ffmpeg(log, progress):
    if _copy_bundled_ffmpeg(log) and ffmpeg_ready()[0]:
        return
    work = Path(tempfile.mkdtemp(prefix="ffmpeg-", dir=data_dir()))
    try:
        zip_path = work / "ffmpeg.zip"
        _download(FFMPEG_URL, zip_path, log, progress, "FFmpeg")
        progress(1, 1, "Extracting FFmpeg")
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                name = Path(member).name
                if name in ("ffmpeg.exe", "ffprobe.exe"):
                    with archive.open(member) as src, open(engine_dir() / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        log("FFmpeg installed next to the engine.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- scanning ----------
class Options:
    def __init__(self, recursive=True, percent=95, audio=False, audio_ratio=0.10, audio_similarity=0.80,
                 visual=False, visual_hit=89):
        self.recursive = recursive
        self.percent = percent
        self.audio = audio
        self.audio_ratio = audio_ratio
        self.audio_similarity = audio_similarity
        self.visual = visual
        self.visual_hit = visual_hit


class ScanState:
    """Holds the running engine process so the Cancel button can stop it from the UI thread."""

    def __init__(self):
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        proc = self.proc
        if proc and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               creationflags=_NO_WINDOW, capture_output=True)
            else:
                proc.kill()


def build_command(engine, folders, options, db_path, out_file):
    cmd = [engine, "scan-and-compare"]
    for folder in folders:
        cmd += ["-i", str(folder)]
    if not options.recursive:
        cmd.append("--no-subdirs")
    cmd += ["--percent", f"{options.percent:g}", "--db", str(db_path),
            "--format", "json", "--output", str(out_file)]
    if options.audio:
        cmd += ["--partial-clip-detection",
                "--partial-clip-min-ratio", f"{options.audio_ratio:.2f}",
                "--partial-clip-similarity", f"{options.audio_similarity:.2f}"]
    if options.visual:
        cmd += ["--ai-partial", "--ai-partial-hit-percent", f"{options.visual_hit:g}"]
    return cmd


STAGE_RE = re.compile(r"\(([^()]*?)\s+(\d+)/(\d+)\)\s*$")  # trailing "(Hashing 3/100)" on a progress line
POS_RE = re.compile(r"\]\s+(\d+)/(\d+)")                  # the overall "pos/max" after the percentage


def parse_progress(line):
    """(done, total, stage) from a progress line, or None. The engine restarts its count for each stage,
    so the stage's own numbers are used when it reports them; otherwise the overall count."""
    if not PROGRESS_RE.search(line):
        return None
    stage = STAGE_RE.search(line)
    if stage:
        return int(stage.group(2)), int(stage.group(3)), stage.group(1).strip() or "Scanning"
    pos = POS_RE.search(line)
    if pos:
        return int(pos.group(1)), int(pos.group(2)), "Scanning"
    return None


def run_engine(cmd, state, log, progress):
    """Run the CLI, stream its output to the log and report progress. Returns the exit code."""
    state.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    try:
        # Progress is written with carriage returns, so split on both \r and \n.
        buffer = ""
        last = None
        while True:
            chunk = state.proc.stderr.read(512)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            parts = re.split(r"[\r\n]", buffer)
            buffer = parts.pop()
            for line in parts:
                line = line.strip()
                if not line:
                    continue
                parsed = parse_progress(line)
                if parsed:
                    done, total, stage = parsed
                    if (done, total, stage) != last and total > 0:
                        last = (done, total, stage)
                        progress(done, total, stage)
                elif not line.startswith("Results written"):
                    log(line)
        state.proc.stdout.read()  # drain
        code = state.proc.wait()
    finally:
        state.proc = None
    return code


def _timespan_seconds(value):
    """System.Text.Json writes TimeSpan as [d.]hh:mm:ss[.fffffffff]. Returns seconds or 0."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^(-)?(?:(\d+)\.)?(\d+):(\d+):(\d+)(?:\.(\d+))?$", str(value))
    if not m:
        return 0.0
    sign = -1 if m.group(1) else 1
    days = int(m.group(2) or 0)
    seconds = days * 86400 + int(m.group(3)) * 3600 + int(m.group(4)) * 60 + int(m.group(5))
    frac = float("0." + m.group(6)) if m.group(6) else 0.0
    return sign * (seconds + frac)


def _flag_names(value):
    """Flags come out as a string such as 'PartialClip, AiMatched', or as a number."""
    if isinstance(value, int):
        names = set()
        for bit, name in ((2, "PartialClip"), (4, "AiMatched"), (1, "Flipped"), (8, "GrayscaleMatched"),
                          (16, "PHashMatched")):
            if value & bit:
                names.add(name)
        return names
    return {p.strip() for p in str(value or "").split(",") if p.strip() and p.strip() != "None"}


def match_type(item):
    flags = _flag_names(item.get("Flags"))
    if "PartialClip" in flags:
        return "partial_visual" if "AiMatched" in flags else "partial_audio"
    if "AiMatched" in flags:
        return "near"
    return "exact" if float(item.get("Similarity") or 0) >= 99.99 else "near"


def _normal(path):
    return os.path.normcase(os.path.abspath(str(path)))


def group_key(paths):
    return hashlib.sha1("\n".join(sorted(_normal(p) for p in paths)).encode("utf-8")).hexdigest()


def read_results(json_path):
    """Groups as plain dicts with clean fields. Each group's items have 'best' set on the best copy."""
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)
    groups = []
    for g in raw:
        items = []
        for it in g.get("Items", []):
            items.append({
                "path": it.get("Path", ""),
                "folder": it.get("Folder") or str(Path(it.get("Path", "")).parent),
                "name": Path(it.get("Path", "")).name,
                "size": int(it.get("SizeLong") or 0),
                "resolution": it.get("FrameSize") or "",
                "pixels": int(it.get("FrameSizeInt") or 0),
                "duration": _timespan_seconds(it.get("Duration")),
                "bitrate": float(it.get("BitRateKbs") or 0),
                "similarity": float(it.get("Similarity") or 0),
                "offset": _timespan_seconds(it.get("PartialClipOffset")),
                "match": match_type(it),
                "best": False,
                "flags": _flag_names(it.get("Flags")),
            })
        if len(items) < 2:
            continue
        best = max(items, key=lambda i: (i["pixels"], i["bitrate"], i["size"]))
        best["best"] = True
        groups.append({"key": group_key([i["path"] for i in items]), "items": items})
    return groups


def group_match(group):
    """A group's match type: the type of its copies that are not the best copy."""
    others = [i["match"] for i in group["items"] if not i["best"]]
    return others[0] if others else group["items"][0]["match"]


def filter_ignored(groups, ignored):
    ignored = set(ignored)
    return [g for g in groups if g["key"] not in ignored]


# ---------- single-file checks (Mode B) ----------
def check_files_against_library(files, library, cfg, state, log, progress, db_path):
    """Scan the library together with a temp folder holding hardlinks (or copies) of the picked files,
    then keep only groups that contain a picked file. The temp folder is always removed afterwards."""
    engine = find_engine()
    temp = data_dir() / "tmp" / uuid.uuid4().hex
    temp.mkdir(parents=True)
    picked = {}  # temp path (normalised) -> original path
    try:
        for index, original in enumerate(files):
            target = temp / f"{index:03d}_{Path(original).name}"
            try:
                os.link(original, target)  # same drive: no extra disk space
                how = "hardlink"
            except OSError:
                shutil.copy2(original, target)  # other drive: a plain copy
                how = "copy"
            picked[_normal(target)] = str(original)
            log(f"Prepared {Path(original).name} as a {how} for the check.")

        out_file = temp / "results.json"
        cmd = build_command(engine, [library, temp], cfg, db_path, out_file)
        code = run_engine(cmd, state, log, progress)
        if state.cancelled:
            return []
        if code != 0 or not out_file.exists():
            raise RuntimeError(f"The engine stopped with code {code}. See the lines above.")
        groups = read_results(out_file)
    finally:
        shutil.rmtree(temp, ignore_errors=True)  # only our temp links/copies; the originals are untouched

    kept = []
    for group in groups:
        has_picked = any(_normal(i["path"]) in picked for i in group["items"])
        if not has_picked:
            continue  # drop duplicates that exist only inside the library
        items = []
        originals = {_normal(v) for v in picked.values()}
        for item in group["items"]:
            key = _normal(item["path"])
            if key in picked:
                original = picked[key]
                item = dict(item, path=original, name=Path(original).name, folder=str(Path(original).parent),
                            picked=True)
            elif _normal(item["path"]) in originals:
                continue  # the library copy of a picked file would show up twice
            items.append(item)
        if len(items) >= 2:
            kept.append({"key": group_key([i["path"] for i in items]), "items": items})
    return kept


# ---------- acting on results ----------
DELETE_LOG_HEADER = ["timestamp", "action", "deleted_path", "size_bytes", "kept_path", "match", "similarity"]


def delete_log_path():
    return data_dir() / "deletions.csv"


def keep_one(group, keep_path, log):
    """Send every other copy in the group to the Recycle Bin and log it. Returns how many were sent."""
    from send2trash import send2trash
    log_file = delete_log_path()
    write_header = not log_file.exists()
    sent = 0
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(DELETE_LOG_HEADER)
        for item in group["items"]:
            if _normal(item["path"]) == _normal(keep_path):
                continue
            if not os.path.exists(item["path"]):
                log(f"Skipped (already gone): {item['path']}")
                continue
            size = os.path.getsize(item["path"])
            send2trash(item["path"])
            writer.writerow([datetime.now().isoformat(timespec="seconds"), "Recycle Bin", item["path"], size,
                             keep_path, item["match"], f"{item['similarity']:.2f}"])
            log(f"Recycle Bin: {item['path']}")
            sent += 1
    return sent


def extract_thumbnail(path, duration, width=160):
    """A PIL image of a frame from the middle of the video, or None."""
    from gif_maker import extract_frame
    return extract_frame(path, max(duration / 2, 0), max_width=width)


def format_seconds(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

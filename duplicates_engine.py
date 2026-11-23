"""Duplicate video detection. Wraps the vdf-cli engine from 0x90d/videoduplicatefinder (AGPLv3).

The engine is NOT bundled with this app. It is downloaded when you ask, into the engine storage place
(Models\\vdf-cli beside the app), and the bundled FFmpeg is copied into Models\\ffmpeg for it. Nothing here
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

import fileops
import jobs
import movelog
import net
import paths
import settings

REPO = "0x90d/videoduplicatefinder"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
EXE = ".exe" if sys.platform == "win32" else ""
ENGINE_NAME = "vdf-cli" + EXE
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
    """Small files: last results, the deletions log."""
    return paths.place("data")


def engine_dir():
    return paths.place("engine")


def ffmpeg_dir():
    return paths.place("ffmpeg")


def db_path():
    return paths.place("fingerprints") / "fingerprints.db"


def temp_dir():
    return paths.place("temp")


def find_engine():
    """The installed vdf-cli, or None."""
    folder = paths.BY_KEY["engine"].path()
    if not folder.exists():
        return None
    found = sorted(folder.rglob(ENGINE_NAME))
    return str(found[0]) if found else None


def installed_version():
    return settings.load().get("dup_engine_version", "")


def _ffmpeg_in(folder):
    return all((Path(folder) / (n + EXE)).exists() for n in ("ffmpeg", "ffprobe"))


def ffmpeg_ready():
    """The engine needs FFmpeg and FFprobe in the FFmpeg place or on PATH. Returns (ok, message)."""
    if _ffmpeg_in(paths.BY_KEY["ffmpeg"].path()):
        return True, "Found"
    if getattr(sys, "_MEIPASS", None) and _ffmpeg_in(sys._MEIPASS):
        return True, "Bundled with the app (copied for the engine when a scan starts)"
    missing = [n for n in ("ffmpeg", "ffprobe") if not shutil.which(n)]
    if missing:
        return False, "Missing " + " and ".join(missing)
    return True, "Found on PATH"


def prepare_ffmpeg(log):
    """The .exe ships with FFmpeg and FFprobe. Copy them into the FFmpeg place so the engine can use them."""
    base = getattr(sys, "_MEIPASS", None)
    if not base or _ffmpeg_in(paths.BY_KEY["ffmpeg"].path()):
        return False
    folder = ffmpeg_dir()
    for name in ("ffmpeg", "ffprobe"):
        src = Path(base) / (name + EXE)
        if src.exists():
            shutil.copy2(src, folder / (name + EXE))
    log(f"Copied the FFmpeg bundled with this app to {folder} for the engine.")
    return True


def engine_env():
    """The engine finds FFmpeg on PATH: put the FFmpeg place first."""
    import procenv
    env = procenv.clean()
    env["PATH"] = str(paths.BY_KEY["ffmpeg"].path()) + os.pathsep + env.get("PATH", "")
    return env


# ---------- downloads (STANDARDS.md: say what, how big and where before downloading) ----------
def download(url, dest, log, progress, label):
    """Download with progress in bytes (the status bar shows MB and MB/s). Writes to a .part file first."""
    request = urllib.request.Request(url, headers={"User-Agent": "MediaToolbox"})
    part = Path(str(dest) + ".part")
    with net.urlopen(request, timeout=60) as response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        progress(0, total, f"Downloading {label}", size=True)
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            progress(done, total, f"Downloading {label}", size=True)
    os.replace(part, dest)
    log(f"Downloaded {label} ({done / 1048576:.1f} MB).")


def latest_release():
    """Tag name and asset list of the newest engine release."""
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": "MediaToolbox",
                                                            "Accept": "application/vnd.github+json"})
    with net.urlopen(request, timeout=30) as response:
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


def lookup_engine(log=print, progress=None):
    """What would be downloaded: {"tag", "name", "size", "url", "dest"}. Nothing is downloaded yet."""
    if progress:
        progress(0, 0, "Asking GitHub for the newest engine")
    tag, assets = latest_release()
    asset = pick_cli_asset(assets)
    info = {"tag": tag, "name": asset["name"], "size": int(asset.get("size") or 0),
            "url": asset["browser_download_url"], "dest": str(paths.BY_KEY["engine"].path())}
    log(f"Newest engine: {tag} ({asset['name']}, {info['size'] / 1048576:.1f} MB).")
    return info


def install_engine(info, log, progress):
    """Download and unpack the engine described by lookup_engine()."""
    work = Path(tempfile.mkdtemp(prefix="vdf-", dir=temp_dir()))
    try:
        zip_path = work / "engine.zip"
        download(info["url"], zip_path, log, progress, f"{info['name']} ({info['tag']})")
        progress(0, 0, "Unpacking the engine")
        target = engine_dir()
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(target)
        if not find_engine():
            raise RuntimeError(f"{ENGINE_NAME} wasn't in the downloaded zip")
        settings.save({"dup_engine_version": info["tag"]})
        log(f"Engine {info['tag']} installed in {target}.")
    finally:
        shutil.rmtree(work, ignore_errors=True)  # the app's own working folder
    prepare_ffmpeg(log)
    return {"summary": f"engine {info['tag']} installed"}


def lookup_ffmpeg(log=print, progress=None):
    """Size of the FFmpeg download, for the question before downloading (runs from source only)."""
    request = urllib.request.Request(FFMPEG_URL, method="HEAD", headers={"User-Agent": "MediaToolbox"})
    size = 0
    try:
        with net.urlopen(request, timeout=30) as response:
            size = int(response.headers.get("Content-Length") or 0)
    except Exception:
        pass
    return {"name": "FFmpeg essentials (gyan.dev)", "size": size, "url": FFMPEG_URL,
            "dest": str(paths.BY_KEY["ffmpeg"].path())}


def install_ffmpeg(info, log, progress):
    if prepare_ffmpeg(log):
        return {"summary": "FFmpeg ready"}
    work = Path(tempfile.mkdtemp(prefix="ffmpeg-", dir=temp_dir()))
    try:
        zip_path = work / "ffmpeg.zip"
        download(info["url"], zip_path, log, progress, info["name"])
        progress(0, 0, "Unpacking FFmpeg")
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                name = Path(member).name
                if name in ("ffmpeg.exe", "ffprobe.exe"):
                    with archive.open(member) as src, open(ffmpeg_dir() / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        log(f"FFmpeg installed in {ffmpeg_dir()}.")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"summary": "FFmpeg installed"}


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


def _process_tree(root_pid):
    """The pid and every child process below it (the engine starts FFmpeg and other helpers)."""
    if sys.platform != "win32":
        return [root_pid]
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = kernel.CreateToolhelp32Snapshot(0x2, 0)  # all processes
    children = {}
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        ok = kernel.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            ok = kernel.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snap)
    found, todo = [], [root_pid]
    while todo:
        pid = todo.pop()
        if pid in found:
            continue
        found.append(pid)
        todo.extend(children.get(pid, []))
    return found


def _suspend(pid, resume):
    """Pause (or continue) one process without ending it."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
        fn.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
        if handle:
            try:
                fn(handle)
            finally:
                kernel.CloseHandle(handle)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGCONT if resume else signal.SIGSTOP)
        except OSError:
            pass


class ScanState:
    """Pauses and continues the running engine (the job's pause target). Stop is handled by the job, which ends
    the engine and everything it started. Stopping keeps the work done so far: the engine saves its
    fingerprints every minute, and the next scan skips everything already in the database."""

    def __init__(self):
        self.proc = None
        self.paused = False

    @property
    def cancelled(self):
        job = jobs.current()
        return bool(job and job.stop_requested)

    def pause(self):
        proc = self.proc
        if proc and proc.poll() is None and not self.paused:
            for pid in _process_tree(proc.pid):
                _suspend(pid, resume=False)
            self.paused = True

    def resume(self):
        proc = self.proc
        if proc and proc.poll() is None and self.paused:
            for pid in _process_tree(proc.pid):
                _suspend(pid, resume=True)
        self.paused = False


def build_command(engine, folders, options, db, out_file, gpu=False):
    cmd = [engine, "scan-and-compare"]
    for folder in folders:
        cmd += ["-i", str(folder)]
    if not options.recursive:
        cmd.append("--no-subdirs")
    cmd += ["--percent", f"{options.percent:g}", "--db", str(db),
            "--checkpoint-interval", "1",  # save fingerprints every minute, so stopping loses little
            "--format", "json", "--output", str(out_file)]
    if gpu:
        cmd += ["--hardware-accel", "cuda"]
    if options.audio:
        cmd += ["--partial-clip-detection",
                "--partial-clip-min-ratio", f"{options.audio_ratio:.2f}",
                "--partial-clip-similarity", f"{options.audio_similarity:.2f}"]
    if options.visual:
        cmd += ["--ai-partial", "--ai-partial-hit-percent", f"{options.visual_hit:g}"]
    return cmd


STAGE_RE = re.compile(r"\(([^()]*?)\s+(\d+)/(\d+)\)\s*$")  # trailing "(Hashing 3/100)" on a progress line
POS_RE = re.compile(r"\]\s+(\d+)/(\d+)")                  # the overall "pos/max" after the percentage
ETA_RE = re.compile(r"(?:ETA|remaining)[:\s]+(\d+):(\d{2}):(\d{2})", re.I)


def parse_progress(line):
    """(done, total, stage, eta seconds or None) from a progress line, or None. The engine restarts its count
    for each stage, so the stage's own numbers are used when it reports them; otherwise the overall count."""
    if not PROGRESS_RE.search(line):
        return None
    eta = None
    m = ETA_RE.search(line)
    if m:
        eta = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    stage = STAGE_RE.search(line)
    if stage:
        return int(stage.group(2)), int(stage.group(3)), stage.group(1).strip() or "Scanning", eta
    pos = POS_RE.search(line)
    if pos:
        return int(pos.group(1)), int(pos.group(2)), "Scanning", eta
    return None


def run_engine(cmd, state, log, progress):
    """Run the CLI, stream its output to the log and report progress. Returns the exit code.
    progress(done, total, stage, eta) gets the stage's own count and the engine's own time estimate."""
    state.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=_NO_WINDOW, env=engine_env())
    jobs.register_process(state.proc)
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
                    done, total, stage, eta = parsed
                    if (done, total, stage) != last and total > 0:
                        last = (done, total, stage)
                        try:
                            progress(done, total, stage, eta)
                        except jobs.JobStopped:
                            pass  # the job is ending the engine; keep draining its output
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


def group_key(paths_):
    return hashlib.sha1("\n".join(sorted(_normal(p) for p in paths_)).encode("utf-8")).hexdigest()


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


# ---------- saved results ----------
def _plain(groups):
    return [{"key": g["key"], "items": [dict(i, flags=sorted(i.get("flags", ()))) for i in g["items"]]}
            for g in groups]


def _from_plain(plain):
    groups = []
    for g in plain or []:
        items = [dict(i, flags=set(i.get("flags", ()))) for i in g.get("items", []) if Path(i["path"]).exists()]
        if len(items) >= 2:
            if not any(i.get("best") for i in items):
                max(items, key=lambda i: (i["pixels"], i["bitrate"], i["size"]))["best"] = True
            groups.append({"key": g["key"], "items": items})
    return groups


def save_results(kind, groups):
    """kind: "folder" or "library". Kept so results are still there after the app is closed."""
    try:
        fileops.write_json(data_dir() / f"{kind}_results.json", _plain(groups))
    except OSError:
        pass


def load_results(kind):
    return _from_plain(fileops.read_json(data_dir() / f"{kind}_results.json", []))


# ---------- one or more picked videos against a library ----------
def check_files_against_library(files, library, cfg, state, log, progress, db, gpu=False):
    """Scan the library together with a temp folder holding hardlinks (or copies) of the picked files,
    then keep only groups that contain a picked file. The temp folder is always removed afterwards."""
    engine = find_engine()
    temp = temp_dir() / uuid.uuid4().hex
    temp.mkdir(parents=True)
    picked = {}  # temp path (normalised) -> original path
    try:
        for index, original in enumerate(files):
            target = temp / f"{index:03d}_{Path(original).name}"
            try:
                os.link(original, target)  # same drive: no extra disk space
                how = "link"
            except OSError:
                shutil.copy2(original, target)  # another drive: a plain copy
                how = "copy"
            picked[_normal(target)] = str(original)
            log(f"Prepared {Path(original).name} as a {how} for the check.")
        out_file = temp / "results.json"
        cmd = build_command(engine, [library, temp], cfg, db, out_file, gpu)
        code = run_engine(cmd, state, log, progress)
        if state.cancelled:
            return None
        if code != 0 or not out_file.exists():
            raise EngineFailed(code)
        groups = read_results(out_file)
    finally:
        shutil.rmtree(temp, ignore_errors=True)  # only our temp links/copies; the originals are untouched

    kept = []
    originals = {_normal(v) for v in picked.values()}
    for group in groups:
        if not any(_normal(i["path"]) in picked for i in group["items"]):
            continue  # drop duplicates that exist only inside the library
        items = []
        for item in group["items"]:
            key = _normal(item["path"])
            if key in picked:
                original = picked[key]
                item = dict(item, path=original, name=Path(original).name, folder=str(Path(original).parent),
                            picked=True)
            elif key in originals:
                continue  # the library copy of a picked file would show up twice
            items.append(item)
        if len(items) >= 2:
            kept.append({"key": group_key([i["path"] for i in items]), "items": items})
    return kept


class EngineFailed(RuntimeError):
    def __init__(self, code):
        super().__init__(f"The engine stopped with code {code}. The log shows its last lines.")
        self.code = code


# ---------- acting on results ----------
DELETE_LOG_HEADER = ["timestamp", "action", "deleted_path", "size_bytes", "kept_path", "match", "similarity"]


def delete_log_path():
    return data_dir() / "deletions.csv"


def recycle_files(entries, log, progress=None):
    """entries: [(path, kept_path, match, similarity)]. Sends each to the Recycle Bin (never a permanent
    delete) and writes it to deletions.csv. Stops at the first file the Recycle Bin can't take.
    Returns the paths sent."""
    log_file = delete_log_path()
    write_header = not log_file.exists()
    sent = []
    total = len(entries)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(DELETE_LOG_HEADER)
        for n, (path, kept, match, similarity) in enumerate(entries):
            if progress:
                progress(n, total, f"Sending {Path(path).name} to the Recycle Bin")
            if not os.path.exists(path):
                log(f"Skipped (already gone): {path}")
                continue
            size = os.path.getsize(path)
            fileops.recycle(path)  # raises RecycleError: the file stays and we stop
            writer.writerow([datetime.now().isoformat(timespec="seconds"), "Recycle Bin", path, size, kept or "",
                             match or "", f"{similarity:.2f}" if similarity else ""])
            f.flush()
            log(f"Recycle Bin: {path}")
            sent.append(path)
    return sent


def keep_one_entries(group, keep_path):
    """The recycle entries for "keep this copy": every other copy in the group."""
    return [(i["path"], keep_path, i["match"], i["similarity"]) for i in group["items"]
            if _normal(i["path"]) != _normal(keep_path)]


def format_seconds(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def plan_moves(groups, group_keys, file_paths, target):
    """What to move or copy, and where it goes inside the chosen folder.

    - A file in a chosen group goes into that group's subfolder ("Group N - name"). If the file is in more
      than one group, it's copied (not moved), so every group keeps its own copy.
    - A file chosen on its own goes into the top of the folder (copied if it's in several groups).
    Returns [{"src", "dst_dir", "copy"}] for the review dialog."""
    membership = {}
    for group in groups:
        for item in group["items"]:
            k = _normal(item["path"])
            membership[k] = membership.get(k, 0) + 1
    ops, handled = [], set()
    for number, group in enumerate(groups, 1):
        if group["key"] not in group_keys:
            continue
        best = next((i for i in group["items"] if i["best"]), group["items"][0])
        sub = f"Group {number} - {Path(best['path']).stem}"
        for item in group["items"]:
            k = _normal(item["path"])
            ops.append({"src": item["path"], "dst_dir": str(Path(target) / sub), "copy": membership.get(k, 0) > 1})
            handled.add(k)
    for path in file_paths:
        k = _normal(path)
        if k in handled:
            continue
        handled.add(k)
        ops.append({"src": path, "dst_dir": str(target), "copy": membership.get(k, 0) > 1})
    return ops


def execute_moves(ops, log, progress=None):
    """Carry out the reviewed moves; a taken name gets " (2)". Every move and copy goes into the move log so
    it can be undone. Returns the source paths that were moved (copies leave their source in place)."""
    moved, done = [], []
    total = len(ops)
    try:
        for n, op in enumerate(ops):
            src = Path(op["src"])
            if progress:
                progress(n, total, f"{'Copying' if op['copy'] else 'Moving'} {src.name}")
            if not src.exists():
                log(f"Skipped (already gone): {src}")
                continue
            if op["copy"]:
                dst = fileops.copy_file(src, op["dst_dir"])
                done.append(("copy", src, dst))
                log(f"Copied {src.name} \u2192 {dst}")
            else:
                dst = fileops.move_file(src, op["dst_dir"])
                done.append(("move", src, dst))
                moved.append(str(src))
                log(f"Moved {src.name} \u2192 {dst}")
    finally:
        movelog.record("Duplicate videos", f"Moved {len(moved)} and copied {len(done) - len(moved)} duplicate(s)",
                       done)
    return moved

"""Logs on disk, crash logs and safe mode (STANDARDS.md: "The log" and "Crash safety").

- Each run writes logs/run-<date>-<time>.txt; the newest 10 are kept.
- Long jobs (installs, big scans) get their own file in logs/jobs/, named in the app's log.
- Unhandled errors write logs/crash-<date>.txt with what was happening and the last log lines.
- Native crashes are caught by faulthandler into logs/crash-native-<date>.txt.
- After two unclean exits in a row, the app starts in safe mode."""
import faulthandler
import re
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

import fileops
import paths

KEEP_RUNS = 10
_lock = threading.Lock()
_run_file = None
_recent = deque(maxlen=80)
_context = lambda: ""  # noqa: E731  set by the window: what is running now
_native_file = None


def start_run_log():
    global _run_file
    folder = paths.logs_dir()
    _run_file = folder / time.strftime("run-%Y%m%d-%H%M%S.txt")
    runs = sorted(folder.glob("run-*.txt"))
    for old in runs[:-KEEP_RUNS + 1]:
        try:
            old.unlink()  # the app's own old logs
        except OSError:
            pass
    return _run_file


def write(line):
    stamped = f"{time.strftime('%H:%M:%S')}  {line}"
    _recent.append(stamped)
    if _run_file is None:
        return
    with _lock:
        try:
            with open(_run_file, "a", encoding="utf-8") as f:
                f.write(stamped + "\n")
        except OSError:
            pass


def run_log_path():
    return _run_file


class JobLog:
    """A log file of its own for one long job."""

    def __init__(self, name):
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "job"
        folder = paths.ensure(paths.logs_dir() / "jobs")
        self.path = folder / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.txt"

    def write(self, line):
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')}  {line}\n")
        except OSError:
            pass


def set_context(fn):
    global _context
    _context = fn


def write_crash(kind, exc_type, exc, tb):
    path = paths.logs_dir() / time.strftime("crash-%Y%m%d-%H%M%S.txt")
    try:
        doing = _context()
    except Exception:
        doing = "unknown"
    text = [f"Media Toolbox crash ({kind}) at {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"What was happening: {doing or 'nothing running'}", "",
            "".join(traceback.format_exception(exc_type, exc, tb)), "Last log lines:"] + list(_recent)
    try:
        path.write_text("\n".join(text), encoding="utf-8")
    except OSError:
        pass
    write(f"ERROR: unexpected error ({exc_type.__name__}: {exc}). Details are in {path}.")
    return path


def install_crash_handlers(on_error=None):
    """Write crash logs for unhandled errors. on_error(path) lets the window say what happened."""
    global _native_file

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return sys.__excepthook__(exc_type, exc, tb)
        path = write_crash("error", exc_type, exc, tb)
        if on_error:
            try:
                on_error(path)
            except Exception:
                pass

    def thread_hook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    try:
        _native_file = open(paths.logs_dir() / time.strftime("crash-native-%Y%m%d-%H%M%S.txt"), "w", encoding="utf-8")
        faulthandler.enable(_native_file)
    except (OSError, RuntimeError, ValueError):
        pass


def close_native_log():
    """On a clean exit, drop the empty native crash file."""
    global _native_file
    if _native_file is None:
        return
    try:
        faulthandler.disable()
        name = _native_file.name
        _native_file.close()
        if Path(name).stat().st_size == 0:
            Path(name).unlink()
    except (OSError, ValueError):
        pass
    _native_file = None


# ----- safe mode: two unclean exits in a row -----
def _session_file():
    return paths.place("data") / "session.json"


def begin_session():
    """Returns how many unclean exits came before this start (0 after a clean exit)."""
    state = fileops.read_json(_session_file(), {})
    unclean = int(state.get("unclean", 0))
    if state.get("running"):
        unclean += 1
    try:
        fileops.write_json(_session_file(), {"running": True, "unclean": unclean})
    except OSError:
        pass
    return unclean


def end_session():
    try:
        fileops.write_json(_session_file(), {"running": False, "unclean": 0})
    except OSError:
        pass


def recent_lines():
    return list(_recent)

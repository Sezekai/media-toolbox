"""Where Media Toolbox keeps things (STANDARDS.md, section 3).

    <root>\\App\\MediaToolbox.exe     the program, replaced by each update
    <root>\\Models\\                  the duplicate engine and the FFmpeg copy it uses
    <root>\\Fingerprints\\            the duplicate engine's fingerprint database (can grow past 100 MB)
    <root>\\Cache\\                   thumbnails and temporary files (safe to delete)
    %LOCALAPPDATA%\\Media Toolbox\\   settings, appearance, results, move log, logs, added fonts

The root is the folder above the program when the program sits in a folder called App, otherwise the
program's own folder. Run from source, the root is dev-root inside the repo. MEDIATOOLBOX_ROOT and
MEDIATOOLBOX_DATA replace the root and the data folder, so tests never touch real data.
Every place can be moved in Settings -> Storage; the choice is stored in settings.json ("storage")."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = "Media Toolbox"
ENV_ROOT = "MEDIATOOLBOX_ROOT"
ENV_DATA = "MEDIATOOLBOX_DATA"
POINTER = "location.json"  # in the default data folder: where the data folder was moved to


def frozen():
    return bool(getattr(sys, "frozen", False))


def program_dir():
    return Path(sys.executable).resolve().parent if frozen() else Path(__file__).resolve().parent


def bundle_dir():
    """Where files bundled into the .exe are unpacked (fonts, FFmpeg)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def root():
    env = os.environ.get(ENV_ROOT)
    if env:
        return Path(env)
    if not frozen():
        return Path(__file__).resolve().parent / "dev-root"
    here = program_dir()
    return here.parent if here.name.lower() == "app" else here


def default_data_dir():
    env = os.environ.get(ENV_DATA)
    if env:
        return Path(env)
    if not frozen():
        return Path(__file__).resolve().parent / "dev-root" / "LocalData"
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(base) / APP


def data_dir():
    """The small-data folder, following the pointer file if it was moved."""
    default = default_data_dir()
    pointer = default / POINTER
    try:
        moved = json.loads(pointer.read_text(encoding="utf-8")).get("data")
        if moved:
            return Path(moved)
    except (OSError, ValueError, AttributeError):
        pass
    return default


def ensure(path):
    """Create a folder, but only when its drive is there: never quietly make it somewhere else."""
    path = Path(path)
    if drive_missing(path):
        return path
    path.mkdir(parents=True, exist_ok=True)
    return path


def drive_missing(path):
    anchor = Path(path).anchor
    return bool(anchor) and not Path(anchor).exists()


# ----- storage places, as listed in Settings -> Storage -----
class Place:
    def __init__(self, key, title, default, cache=False, note=""):
        self.key, self.title, self._default, self.cache, self.note = key, title, default, cache, note

    def default(self):
        return self._default()

    def path(self):
        override = _overrides().get(self.key)
        return Path(override) if override else self.default()

    def missing(self):
        return drive_missing(self.path())


PLACES = [
    Place("data", "Settings, results, move log and logs", data_dir,
          note="Small files that must survive updates."),
    Place("engine", "Duplicate engine (vdf-cli)", lambda: root() / "Models" / "vdf-cli",
          note="Downloaded when you install it. Its licence (AGPL) doesn't allow bundling."),
    Place("ffmpeg", "FFmpeg for the duplicate engine", lambda: root() / "Models" / "ffmpeg",
          note="A copy of the FFmpeg bundled with the app, beside the engine."),
    Place("fingerprints", "Fingerprint database", lambda: root() / "Fingerprints",
          note="What the engine has learned about each video. Slow to rebuild."),
    Place("thumbs", "Thumbnails", lambda: root() / "Cache" / "thumbs", cache=True,
          note="Pictures for lists and cards. Made again when needed."),
    Place("temp", "Temporary files", lambda: root() / "Cache" / "temp", cache=True,
          note="Working files for library checks. Emptied after each check."),
]
BY_KEY = {p.key: p for p in PLACES}


def _overrides():
    # Read settings.json directly: the settings module itself depends on this one.
    try:
        data = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        storage = data.get("storage", {})
        return storage if isinstance(storage, dict) else {}
    except (OSError, ValueError):
        return {}


def place(key):
    """The folder for a storage place, created if its drive is connected."""
    if key == "data":
        return ensure(data_dir())
    return ensure(BY_KEY[key].path())


def logs_dir():
    return ensure(data_dir() / "logs")


def fonts_dir():
    return ensure(data_dir() / "fonts")


def missing_places():
    return [p for p in PLACES if p.missing()]


def folder_size(path):
    total, count = 0, 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
                count += 1
            except OSError:
                pass
    return total, count


# ----- moving from the old layout (version 1 kept everything in %APPDATA%\Media Toolbox) -----
def old_data_dir():
    base = os.environ.get("APPDATA")
    return Path(base) / APP if base else None


def migrate_old_data(log=print):
    """Move version 1's files into the standard places once. Returns True when something moved."""
    old = old_data_dir()
    if old is None or os.environ.get(ENV_DATA) or not old.exists() or old.resolve() == data_dir().resolve():
        return False
    moved = False
    data = place("data")
    if (old / "settings.json").exists() and not (data / "settings.json").exists():
        try:
            settings = json.loads((old / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        for key in ("dup_engine_path", "theme", "font_family", "font_size", "size", "corner_style"):
            settings.pop(key, None)  # absolute engine path and version 1's appearance choices no longer apply
        _write_json(data / "settings.json", settings)
        (old / "settings.json").unlink()
        log(f"Moved settings from {old} to {data}.")
        moved = True
    dup = old / "duplicates"
    if dup.exists():
        targets = {"engine": place("engine")}
        for child in list(dup.iterdir()):
            try:
                if child.name == "engine":
                    _merge(child, targets["engine"])
                elif child.name == "tmp":
                    shutil.rmtree(child, ignore_errors=True)  # the app's own temporary files
                elif child.name in ("deletions.csv", "library_results.json", "last_scan.json"):
                    if not (data / child.name).exists():
                        shutil.move(str(child), str(data / child.name))
                else:
                    target = place("fingerprints")
                    if not (target / child.name).exists():
                        shutil.move(str(child), str(target / child.name))
                moved = True
            except OSError as exc:
                log(f"Could not move {child} to its new place: {exc}. It was left where it is.")
        log(f"Moved the duplicate engine to {place('engine')} and its fingerprints to {place('fingerprints')}.")
    for folder in (dup, old):
        try:
            folder.rmdir()  # only when empty
        except OSError:
            pass
    return moved


def _merge(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if target.exists():
            continue
        shutil.move(str(child), str(target))
    shutil.rmtree(src, ignore_errors=True)


def _write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)

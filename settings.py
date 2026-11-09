"""The app's settings: one JSON file in the data folder, written safely (temporary file, then rename)."""
import json
import os
import threading

import paths

_lock = threading.Lock()


def path():
    return paths.place("data") / "settings.json"


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # missing or unreadable settings just means the defaults are used


def save(updates):
    """Merge updates into the saved settings. Failing to save is not fatal."""
    with _lock:
        try:
            data = load()
            data.update(updates)
            write(data)
        except Exception:
            pass


def write(data):
    target = path()
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, target)


def reset(keep=()):
    """Every option back to its default; keys in keep stay (for example where storage was moved)."""
    with _lock:
        data = load()
        write({k: v for k, v in data.items() if k in keep})

"""Remembers the user's appearance choices between runs."""
import json
import os


def _path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "Media Toolbox")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # missing or unreadable settings just means the defaults are used


def save(updates):
    """Merge updates into the saved settings. Failing to save is not fatal."""
    try:
        data = load()
        data.update(updates)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

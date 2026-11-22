"""The Downloads tool's lists: the two Twitter bookmark accounts, saved downloads and recent ones.

Kept in <data>\\Downloads\\downloads.json. Each download has its own history file in <data>\\Downloads\\history;
both bookmark accounts share twitter-bookmarks.sqlite3. Deleting a download sends its history to the Recycle
Bin; it never touches the files it downloaded."""
import copy
import threading
import time
import uuid
from pathlib import Path

import fileops
import gdl_engine as ge
import paths

BOOKMARKS_URL = "https://x.com/i/bookmarks"
SHARED_HISTORY = "twitter-bookmarks.sqlite3"
ACCOUNTS = (("main", "Main account"), ("second", "Second account"))
_lock = threading.RLock()


def store_path():
    return paths.ensure(paths.place("data") / "Downloads") / "downloads.json"


def _blank():
    data = {"accounts": {}, "saved": [], "recent": []}
    for key, name in ACCOUNTS:
        data["accounts"][key] = {
            "id": key, "kind": "bookmarks", "name": name, "urls": [BOOKMARKS_URL],
            "options": {"login": "browser", "browser": "firefox", "naming": "original", "layout": "flat",
                        "stop_after": 50, "history": True},
            "twitter_user": "", "seeds": None, "markers": [], "last": None}
    return data


def load():
    with _lock:
        data = fileops.read_json(store_path(), None)
        base = _blank()
        if not isinstance(data, dict):
            return base
        for key in ("saved", "recent"):
            base[key] = [d for d in data.get(key, []) if isinstance(d, dict) and d.get("id")]
        for key, _name in ACCOUNTS:
            got = (data.get("accounts") or {}).get(key)
            if isinstance(got, dict):
                base["accounts"][key].update(got)
                base["accounts"][key]["kind"] = "bookmarks"
                base["accounts"][key]["urls"] = [BOOKMARKS_URL]
        return base


def save(data):
    with _lock:
        fileops.write_json(store_path(), data)


def history_file(src):
    name = SHARED_HISTORY if src.get("kind") == "bookmarks" else f"{src['id']}.sqlite3"
    return ge.history_dir() / name


def new_download(urls=(), options=None, name=""):
    return {"id": uuid.uuid4().hex[:12], "kind": "recent", "name": name, "urls": list(urls),
            "options": dict(options or {}), "last": None, "created": time.time()}


def title(src):
    if src.get("name"):
        return src["name"]
    urls = [u for u in src.get("urls", []) if u.strip()]
    if not urls:
        return "New download"
    u = urls[0].strip()
    short = u.split("://", 1)[-1].removeprefix("www.").rstrip("/")
    return short + (f" +{len(urls) - 1}" if len(urls) > 1 else "")


def find(data, sid):
    for key, _n in ACCOUNTS:
        if data["accounts"][key]["id"] == sid:
            return data["accounts"][key]
    for group in ("saved", "recent"):
        for src in data[group]:
            if src["id"] == sid:
                return src
    return None


def put(src):
    """Save one download (an account, a saved one or a recent one) into the store."""
    with _lock:
        data = load()
        src = copy.deepcopy(src)
        if src.get("kind") == "bookmarks":
            data["accounts"][src["id"]] = src
        else:
            group = "saved" if src.get("kind") == "saved" else "recent"
            other = "recent" if group == "saved" else "saved"
            data[other] = [s for s in data[other] if s["id"] != src["id"]]
            items = data[group]
            for n, s in enumerate(items):
                if s["id"] == src["id"]:
                    items[n] = src
                    break
            else:
                items.insert(0, src)
        save(data)
        return src


def remove(sid, log=print):
    """Take a saved or recent download off the list and send its history to the Recycle Bin."""
    with _lock:
        data = load()
        src = find(data, sid)
        if src is None or src.get("kind") == "bookmarks":
            return False
        for group in ("saved", "recent"):
            data[group] = [s for s in data[group] if s["id"] != sid]
        save(data)
    hist = history_file(src)
    if hist.is_file():
        fileops.recycle(hist)
        log(f"Sent the history of {title(src)} to the Recycle Bin ({hist.name}).")
    return True


def clear_history(src, log=print):
    hist = history_file(src)
    if hist.is_file():
        fileops.recycle(hist)
        log(f"Sent the history of {title(src)} to the Recycle Bin ({hist.name}).")
    if src.get("kind") == "bookmarks":
        with _lock:
            data = load()
            for key, _n in ACCOUNTS:
                data["accounts"][key]["markers"] = []
            save(data)


def copy_history(src_from, src_to):
    """Give a new download (Save as new) the same history as the one it came from."""
    a, b = history_file(src_from), history_file(src_to)
    if a.is_file() and a != b:
        import shutil
        shutil.copy2(a, b)


def same_setup(a, b):
    """True when two downloads fetch the same addresses into the same folder (a recent one is reused)."""
    oa, ob = ge.options(a), ge.options(b)
    return ([u.strip() for u in a.get("urls", [])] == [u.strip() for u in b.get("urls", [])]
            and Path(oa["folder"] or ".") == Path(ob["folder"] or "."))


def seeds_from_folder(folder):
    """Files already in a bookmarks folder: the first run stops when it reaches one of them."""
    if not str(folder or "").strip():
        return []
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.lower().endswith(
        (".part", ".ini", ".db", ".json", ".txt")))

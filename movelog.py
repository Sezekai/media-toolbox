"""The move log (STANDARDS.md: "Every move is logged and can be undone").

Each entry records when, which tool, and every file's from and to. The log lives in the data folder, so it
survives restarts and updates. Undo puts files back; when it can't, it says why."""
import threading
import time
import uuid
from pathlib import Path

import fileops
import paths

_lock = threading.Lock()
_listeners = []


def _file():
    return paths.place("data") / "move-log.json"


def entries():
    """Newest first."""
    data = fileops.read_json(_file(), [])
    return list(reversed(data)) if isinstance(data, list) else []


def _save(newest_first):
    fileops.write_json(_file(), list(reversed(newest_first)))
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


def on_change(fn):
    _listeners.append(fn)


def record(tool, title, items):
    """items: [(op, src, dst)] with op "move" or "copy". Returns the new entry, or None if nothing moved."""
    items = [{"op": op, "src": str(src), "dst": str(dst)} for op, src, dst in items]
    if not items:
        return None
    entry = {"id": uuid.uuid4().hex[:12], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool,
             "title": title, "items": items, "undone": False, "note": ""}
    with _lock:
        current = entries()
        current.insert(0, entry)
        _save(current[:500])  # the newest 500 moves
    return entry


def last_undoable():
    return next((e for e in entries() if not e.get("undone")), None)


def undo(entry_id, log=print):
    """Put an entry's files back. Returns (done, problems): how many files went back, and plain-English notes."""
    with _lock:
        current = entries()
        entry = next((e for e in current if e["id"] == entry_id), None)
        if entry is None:
            return 0, ["That move is no longer in the log."]
        if entry.get("undone"):
            return 0, ["That move was already undone."]
        done, problems = 0, []
        for item in reversed(entry["items"]):
            src, dst = Path(item["src"]), Path(item["dst"])
            if not dst.exists():
                problems.append(f"{dst.name} was moved or removed outside the app, so it can't be put back.")
                continue
            try:
                if item["op"] == "copy":
                    fileops.recycle(dst)  # undoing a copy removes the copy, through the Recycle Bin
                    log(f"Undo: sent the copy {dst} to the Recycle Bin.")
                else:
                    src.parent.mkdir(parents=True, exist_ok=True)
                    target = fileops.unique_path(src.parent, src.name)
                    import shutil
                    shutil.move(str(dst), str(target))
                    if target != src:
                        problems.append(f"{src.name} is back in its folder as {target.name}, because a new "
                                        f"file with its old name is there now.")
                    log(f"Undo: moved {dst} back to {target}.")
                done += 1
            except Exception as exc:
                problems.append(f"{dst.name} couldn't be put back: {exc}")
        entry["undone"] = True
        entry["note"] = f"Undone {time.strftime('%Y-%m-%d %H:%M')}" + (f" ({len(problems)} problem(s))" if problems else "")
        _save(current)
        return done, problems


def clear():
    with _lock:
        _save([])

"""Setting up gallery-dl for the Downloads tool: use the gallery-dl.exe you have, or download the official one.

Nothing downloads without asking: the question names what, how big and where it goes (STANDARDS.md)."""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

import dialogs
import fileops
import gdl_engine as ge
import gdl_store as gs
import jobs
import settings

_listeners = []


def on_change(fn):
    _listeners.append(fn)


def changed():
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


def setup(app):
    """Ask how to get gallery-dl, then do it."""
    choice = dialogs.choose(
        "Set up gallery-dl",
        "The Downloads tool runs gallery-dl, a free program (GPL) by mikf. Use the gallery-dl.exe you already "
        "have, or download the newest official one from GitHub.",
        [("own", "Use my gallery-dl.exe…", "secondary"), ("download", "Download it…", "primary")])
    if choice == "own":
        pick_own(app)
    elif choice == "download":
        install(app)


def pick_own(app):
    start = settings.load().get("gdl_exe") or ""
    chosen, _f = QFileDialog.getOpenFileName(app, "Choose gallery-dl.exe", start,
                                             "gallery-dl (gallery-dl*.exe gallery-dl);;Programs (*.exe)")
    if not chosen:
        return
    found = ge.version(chosen)
    if not found:
        dialogs.error("That isn't gallery-dl", f"{Path(chosen).name} didn't answer like gallery-dl does. "
                      "Choose gallery-dl.exe.")
        return
    settings.save({"gdl_exe": str(Path(chosen))})
    _suggest_folders(Path(chosen).parent)
    app.toast(f"Using your gallery-dl {found}.", "ok")
    changed()


def _suggest_folders(exe_dir):
    """Your gallery-dl folder may already have the bookmark folders: use them when the accounts have none."""
    data = gs.load()
    touched = False
    for key, sub in (("main", "new"), ("second", "new2")):
        acc = data["accounts"][key]
        folder = exe_dir / "gallery-dl" / "twitter" / sub
        if not acc["options"].get("folder") and folder.is_dir():
            acc["options"]["folder"] = str(folder)
            touched = True
    if touched:
        gs.save(data)


def install(app, update=False):
    app.start(jobs.Job("Looking up gallery-dl", lambda log, progress: {"summary": "", "info": ge.lookup(log, progress)},
                       short="Looking up", done=lambda job: _ask(app, job, update),
                       failed=lambda job: dialogs.error("Couldn't reach GitHub", f"gallery-dl's release list "
                                                        f"couldn't be read: {job.error}. Check the internet "
                                                        "connection and try again.")))


def _ask(app, job, update):
    if job.finished != "done" or not isinstance(job.result, dict):
        return
    info = job.result["info"]
    have = ge.version()
    if update and have and info["tag"].lstrip("v") == have.strip().lstrip("v"):
        dialogs.info("gallery-dl is up to date", f"You have the newest version, {have}.", icon_name="check")
        return
    size = fileops.human_size(info["size"]) if info["size"] else "size not known"
    own = settings.load().get("gdl_exe")
    title = f"Update gallery-dl to {info['tag']}?" if have else "Download gallery-dl?"
    text = (f"gallery-dl.exe {info['tag']} ({size}) from github.com/mikf/gallery-dl goes into the folder below. "
            "It's a free program (GPL) that this app runs to download. It isn't part of the app.")
    note = (f"Your own copy ({own}) stays as it is; the app switches to this one." if own else None)
    if not dialogs.ask(title, text, f"Download {size}", items=[(info["dest"], "destination")], note=note,
                       icon_name="download"):
        return
    app.start(jobs.Job(f"Downloading gallery-dl {info['tag']}", ge.install, info, short="Downloading gallery-dl",
                       done=lambda j: (app.toast("gallery-dl is ready.", "ok") if j.finished == "done" else None,
                                       changed())))

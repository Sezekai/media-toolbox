"""Installing and updating the duplicate engine, from Settings or the Duplicates screen.

Nothing downloads without asking: the question names what, how big and where it goes (STANDARDS.md)."""
import dialogs
import duplicates_engine as de
import fileops
import jobs
from version import __version__  # noqa: F401  (kept for the debug report)

_listeners = []


def on_change(fn):
    """fn() runs after the engine is installed or updated."""
    _listeners.append(fn)


def _changed():
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


def install(app, update=False):
    """Look up the newest engine, ask, then download it."""
    app.start(jobs.Job("Looking up the duplicate engine", lambda log, progress: {
        "summary": "", "info": de.lookup_engine(log, progress)}, short="Looking up",
        done=lambda job: _ask_install(app, job, update),
        failed=lambda job: dialogs.error("Couldn't reach GitHub", f"The engine's release list couldn't be read: "
                                         f"{job.error}. Check the internet connection and try again.")))


def _ask_install(app, job, update):
    if job.finished != "done" or not isinstance(job.result, dict):
        return
    info = job.result["info"]
    installed = de.installed_version()
    if update and installed == info["tag"] and de.find_engine():
        dialogs.info("The engine is up to date", f"You have the newest version, {installed}.", icon_name="check")
        return
    size = fileops.human_size(info["size"]) if info["size"] else "size not known"
    title = f"Update the engine to {info['tag']}?" if installed and de.find_engine() else "Download the duplicate engine?"
    text = (f"{info['name']} ({size}) from github.com/0x90d/videoduplicatefinder goes into the folder below. "
            "It's an open-source program (AGPL) that this app runs to find duplicates. It isn't part of the app.")
    if not dialogs.ask(title, text, f"Download {size}", items=[(info["dest"], "destination")], icon_name="duplicate"):
        return
    app.start(jobs.Job(f"Downloading the engine {info['tag']}", de.install_engine, info, short="Downloading engine",
                       done=lambda j: _done(app, j)))


def _done(app, job):
    if job.finished == "done":
        app.toast("The duplicate engine is installed.", "ok")
    _changed()


def install_ffmpeg(app):
    """Only needed when running from source: the .exe brings its own FFmpeg."""
    info = de.lookup_ffmpeg()
    size = fileops.human_size(info["size"]) if info["size"] else "size not known"
    if not dialogs.ask("Download FFmpeg for the engine?", f"{info['name']} ({size}) goes into the folder below.",
                       f"Download {size}", items=[(info["dest"], "destination")], icon_name="duplicate"):
        return
    app.start(jobs.Job("Downloading FFmpeg", de.install_ffmpeg, info, short="Downloading FFmpeg",
                       done=lambda j: _done(app, j)))

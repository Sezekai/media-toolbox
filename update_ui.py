"""Checking for, downloading and starting a new version, from Settings or the banner at start-up."""
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

import dialogs
import jobs
import updater
from version import __version__
from widgets import Banner

_banner = None


def check(app, quiet=False):
    """Look for a newer version. quiet: only speak up when there is one (the daily check at start-up)."""
    app.start(jobs.Job("Checking for updates", lambda log, progress: {"summary": "", "info": updater.latest(log, progress)},
                       short="Updates", done=lambda job: _checked(app, job, quiet),
                       failed=lambda job: None if quiet else dialogs.error(
                           "Couldn't check for updates", f"GitHub couldn't be reached: {job.error}")))


def _checked(app, job, quiet):
    if job.finished != "done" or not isinstance(job.result, dict):
        return
    info = job.result["info"]
    page = app.pages.get("settings")
    if page is not None and hasattr(page, "show_update"):
        page.show_update(info)
    if not info["newer"]:
        if not quiet:
            app.toast(f"You have the newest version, {__version__}.", "ok")
        return
    if quiet:
        _show_banner(app, info)
    else:
        offer(app, info)


def _show_banner(app, info):
    global _banner
    if _banner is not None:
        _banner.hide()
    _banner = Banner(f"Media Toolbox {info['version']} is available.",
                     f"You have {__version__}. It downloads ({updater.size_text(info)}) and replaces this copy.",
                     "Download and restart…", lambda: offer(app, info), "info")
    app.add_banner(_banner)


def offer(app, info):
    if not updater.frozen():
        dialogs.info("Running from source", "This copy runs from the source code, so update it with git pull.",
                     icon_name="info")
        return
    import sys
    from pathlib import Path
    notes = info["notes"].splitlines()[:12]
    if not dialogs.ask(f"Update to Media Toolbox {info['version']}?",
                       f"{info['name']} ({updater.size_text(info)}) downloads from GitHub and replaces this copy. "
                       "Your settings and files stay as they are.",
                       f"Download {updater.size_text(info)}", items=[(str(Path(sys.executable)), "replaced")],
                       note="\n".join(notes) if notes else None, icon_name="info"):
        return
    app.start(jobs.Job(f"Downloading Media Toolbox {info['version']}", updater.install, info, short="Updating",
                       done=lambda job: _installed(app, job)))


def _installed(app, job):
    if job.finished != "done":
        return
    if _banner is not None:
        _banner.hide()
    if dialogs.ask("Restart now?", f"Media Toolbox {job.result['version']} is installed. It starts when the app "
                   "restarts.", "Restart now", cancel="Later", icon_name="check"):
        restart(app)


def restart(app):
    import sys
    server = getattr(app, "instance_server", None)
    if server is not None:
        server.close()  # so the new copy doesn't hand over to this one
    QProcess.startDetached(sys.executable, [])
    app.close()
    QApplication.quit()

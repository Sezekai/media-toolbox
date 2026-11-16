"""Media Toolbox: start-up.

One instance at a time (a second start brings the running window forward), crash logs, safe mode after two
unclean exits, moving version 1's data once, fonts and the look, then the window.
`MediaToolbox.exe --selftest <folder>` opens every screen off-screen, saves pictures and a report, and exits
with 0 when everything worked (the build runs it before publishing)."""
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

import appearance
import dialogs
import gpu
import icons
import logs
import paths
import preview
import settings
import theme
import version
from app_pages import LookPage, SettingsPage
from cover_page import CoverPage
from duplicates_page import DuplicatesPage
from gif_page import GifPage
from shell import MainWindow
from tool_pages import CopyPage, SilentPage, WebpPage, ZipPage
from widgets import Banner, button

TOOLS = [
    ("silent", "Silent videos", "Silent", "silent", SilentPage),
    ("gif", "GIF maker", "GIF", "gif", GifPage),
    ("cover", "Video thumbnails", "Thumbnail", "cover", CoverPage),
    ("dup", "Duplicate videos", "Duplicates", "duplicate", DuplicatesPage),
    ("webp", "WebP to JPG", "WebP", "image", WebpPage),
    ("zip", "Zip subfolders", "Zip", "zip", ZipPage),
    ("copy", "Copy folder structure", "Structure", "copy_folder", CopyPage),
]
BOTTOM = [
    ("look", "Look", "look", LookPage),
    ("settings", "Settings", "settings", SettingsPage),
    ("keys", "Keys", "keys", None),
    ("log", "Log", "log", None),
]
INSTANCE = "MediaToolbox-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")


def _single_instance():
    """True when this is the only copy running. Otherwise asks the running copy to come forward."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE)
    if sock.waitForConnected(400):
        sock.write(b"show")
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return None
    QLocalServer.removeServer(INSTANCE)  # a stale name left by a crash
    server = QLocalServer()
    server.listen(INSTANCE)
    return server


def _bring_forward(window):
    if window.isMinimized():
        window.showNormal()
    window.show()
    window.raise_()
    window.activateWindow()
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = int(window.winId())
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def _app_icon():
    import app_icon
    return app_icon.qicon()


def build_window(safe_mode, early_log):
    window = MainWindow(TOOLS, BOTTOM, safe_mode=safe_mode)
    window.setWindowIcon(_app_icon())
    logs.set_context(lambda: window.queue.current.title if window.queue.current else "")
    window.log(f"Media Toolbox {version.__version__}. Run log: {logs.run_log_path()}")
    for line in early_log:
        window.log(line)
    if safe_mode:
        banner = Banner("Safe mode is on.", "The app closed unexpectedly twice, so GPU decoding, hover previews and "
                        "the custom title bar are off.", "Turn them back on", None, "warn")

        def back_on():
            logs.end_session()
            banner.hide()
            dialogs.info("They're back on next time", "Restart the app to use the GPU, hover previews and the custom "
                         "title bar again.", icon_name="check")
        banner.button.clicked.connect(back_on)
        window.add_banner(banner)
    _drive_banners(window)
    return window


def _drive_banners(window):
    """A storage place on a drive that isn't there: say which, offer Retry or Choose a new place."""
    for place in paths.missing_places():
        banner = Banner("A drive isn't connected.", f"{place.title} is set to {place.path()}. Nothing is made "
                        "anywhere else until it's back.", "Retry", None, "warn")
        choose = button("Choose a new place…", "ghost")
        banner.layout().addWidget(choose)

        def retry(_c=False, b=banner, p=place):
            if not p.missing():
                b.hide()
                window.toast(f"{p.title} is back.", "ok")
            else:
                window.toast("The drive still isn't there.", "warn")

        def new_place(_c=False, b=banner, p=place):
            window.show_page("settings")
            window.pages["settings"].move_place(p)
        banner.button.clicked.connect(retry)
        choose.clicked.connect(new_place)
        window.add_banner(banner)


def selftest(out_dir):
    """Open every screen off-screen, save a picture of each, and check FFmpeg. Exit code 0 means it passed."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report, ok = [f"Media Toolbox {version.__version__} self-test"], True
    os.environ.setdefault(paths.ENV_ROOT, str(out / "root"))
    os.environ.setdefault(paths.ENV_DATA, str(out / "data"))
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        logs.start_run_log()
        loaded = appearance.register_fonts()
        report.append(f"Fonts loaded: {len(loaded)}")
        theme.use(appearance.DEFAULT_THEME)
        theme.apply(app)
        window = build_window(False, [])
        window.resize(1440, 900)
        window.show()
        for key in [t[0] for t in TOOLS] + ["look", "settings"]:
            window.show_page(key)
            end = time.monotonic() + 0.4
            while time.monotonic() < end:
                app.processEvents()
            window.grab().save(str(out / f"{key}.png"))
            report.append(f"Screen {key}: OK")
        for w, h in ((1100, 680), (1440, 900), (1920, 1080), (1100, 420)):
            window.resize(w, h)
            window.keys_popup.open_popup()
            app.processEvents()
            window.grab().save(str(out / f"keys-{w}x{h}.png"))
            window.keys_popup.close_popup()
        report.append("Keyboard shortcuts popup: OK")
        for w, h in ((1100, 680), (1920, 1080)):
            window.resize(w, h)
            app.processEvents()
            window.grab().save(str(out / f"silent-{w}.png"))
        from media_utils import tool_path
        import subprocess
        for tool in ("ffmpeg", "ffprobe"):
            exe = tool_path(tool)
            res = subprocess.run([exe, "-version"], capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            good = res.returncode == 0
            ok &= good
            report.append(f"{tool}: {'OK' if good else 'FAILED'} ({exe})")
        window.close()
    except Exception:
        ok = False
        report.append("FAILED:\n" + traceback.format_exc())
    report.append("PASSED" if ok else "FAILED")
    (out / "selftest.txt").write_text("\n".join(report), encoding="utf-8")
    if sys.stdout:
        print("\n".join(report))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else "selftest"
        sys.exit(selftest(out))
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:  # the taskbar groups the app's windows under its own icon
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sezekai.MediaToolbox")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())
    app.setApplicationName("Media Toolbox")
    app.setApplicationVersion(version.__version__)
    server = _single_instance()
    if server is None:
        return 0
    early = []
    logs.start_run_log()
    window_ref = []
    logs.install_crash_handlers(lambda path: window_ref and window_ref[0].toast(
        f"Something went wrong. The details are saved in {Path(path).name}; the log has more.", "danger", 7))
    unclean = logs.begin_session()
    safe_mode = unclean >= 2 or "--safe" in sys.argv
    gpu.SAFE_MODE = safe_mode
    preview.SAFE_MODE = safe_mode
    try:
        paths.migrate_old_data(early.append)
    except Exception as exc:
        early.append(f"Moving version 1's files didn't finish: {exc}. They were left where they were.")
    appearance.register_fonts()
    store = appearance.load_store()
    theme.use(store["current"])
    theme.apply(app)
    window = build_window(safe_mode, early)
    window_ref.append(window)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), _bring_forward(window)))
    window.instance_server = server
    import update_ui
    import updater
    updater.clean_up()
    if updater.frozen() and updater.due():
        QTimer.singleShot(4000, lambda: update_ui.check(window, quiet=True))
    last = settings.load().get("last_page", "silent")
    window.show_page(last if last in window.pages else "silent")
    window.show()
    code = app.exec()
    logs.close_native_log()
    return code


if __name__ == "__main__":
    sys.exit(main())

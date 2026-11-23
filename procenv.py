"""Environment for programs the app starts (itself after an update, gallery-dl, the duplicate engine).

The app is a one-file PyInstaller program: while it runs it unpacks into a temporary _MEI folder and sets
_PYI_* variables. A program started with those variables (a new copy of the app, or gallery-dl.exe, which is
built the same way) can take them as its own and use this copy's temporary folder, which is deleted when this
copy closes ("Failed to remove temporary directory", then "No such file ... base_library.zip").
PYINSTALLER_RESET_ENVIRONMENT tells the started program to unpack for itself."""
import os


def clean(env=None):
    env = dict(os.environ if env is None else env)
    for key in list(env):
        if key.upper().startswith(("_PYI_", "_MEIPASS")):
            del env[key]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env

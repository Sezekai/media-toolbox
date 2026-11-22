"""Which Twitter/X account your browser is signed in to, read from Firefox's cookies.

You switch accounts in Firefox and gallery-dl downloads with Firefox's cookies, so before downloading a
bookmarks account the app checks Firefox is signed in to that account (by its numeric user ID, from the
"twid" cookie). Only the ID is read; nothing is sent anywhere or saved except the ID itself."""
import configparser
import os
import shutil
import sqlite3
import tempfile
import urllib.parse
from pathlib import Path


def firefox_dir():
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    return Path.home() / ".mozilla" / "firefox"


def profiles():
    """[(name, folder)] of Firefox profiles, the default first."""
    base = firefox_dir()
    ini = base / "profiles.ini"
    found = []
    if ini.is_file():
        cp = configparser.ConfigParser()
        try:
            cp.read(ini, encoding="utf-8")
        except (configparser.Error, OSError):
            return []
        for section in cp.sections():
            if not section.startswith("Profile"):
                continue
            p = cp[section]
            raw = p.get("Path", "")
            folder = base / raw if p.get("IsRelative", "1") == "1" else Path(raw)
            found.append((p.get("Name", folder.name), folder, p.get("Default", "0") == "1"))
    found.sort(key=lambda f: not f[2])
    return [(name, folder) for name, folder, _d in found]


def cookie_db(profile=""):
    """The cookies database gallery-dl would use: the named profile's, else the most recently used one."""
    candidates = []
    for name, folder in profiles():
        db = folder / "cookies.sqlite"
        if db.is_file():
            if profile and profile.lower() in (name.lower(), folder.name.lower(), str(folder).lower()):
                return db
            candidates.append(db)
    if not candidates:
        root = firefox_dir() / "Profiles"
        candidates = list(root.glob("*/cookies.sqlite")) if root.is_dir() else []
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def twitter_user_id(profile=""):
    """The numeric ID of the Twitter/X account Firefox is signed in to, or None (not signed in, no Firefox,
    or the cookies couldn't be read)."""
    db = cookie_db(profile)
    if db is None:
        return None
    with tempfile.TemporaryDirectory(prefix="mt-cookies-") as tmp:
        copy = Path(tmp) / "cookies.sqlite"
        try:
            shutil.copy2(db, copy)  # Firefox keeps the file open; read a copy, with its write-ahead log
            for extra in ("-wal", "-shm"):
                side = Path(str(db) + extra)
                if side.is_file():
                    shutil.copy2(side, Path(str(copy) + extra))
            con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT value, host FROM moz_cookies WHERE name='twid' "
                                   "ORDER BY lastAccessed DESC").fetchall()
            finally:
                con.close()
        except (OSError, sqlite3.Error):
            return None
    for value, host in rows:
        if "x.com" in host or "twitter.com" in host:
            value = urllib.parse.unquote(value or "").strip('"')
            if value.startswith("u="):
                value = value[2:]
            if value.isdigit():
                return value
    return None

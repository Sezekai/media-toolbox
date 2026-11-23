"""gallery-dl: finding or downloading it, building its commands, and running a download in two steps.

gallery-dl (codeberg.org/mikf/gallery-dl, GPL-2.0; it moved there from GitHub) is a separate program. It isn't bundled: the app uses the
gallery-dl.exe you already have, or downloads the official one after asking (STANDARDS.md).

How a run works
1. Scan: gallery-dl walks the page (your bookmarks, a profile…) without downloading anything. Each file it
   reaches is reported as new, or as skipped because it's in this download's history. The scan stops at the
   stop point (below), so the app knows exactly what's new before anything downloads.
2. Download: gallery-dl walks the page again and downloads just those files, so the progress bar has a real
   total. Every finished file goes into the history.

History is gallery-dl's own download archive (an SQLite file). Twitter files are remembered by tweet and
picture number ("twitter<tweet id>_<num>"), never by file name or folder, so moving or sorting files never
makes them download again, and a retweet of something you have is skipped too. Both bookmark accounts share
one history.

Stop point for bookmarks (newest first, so everything new is at the top):
- files you kept from last time (the files in the folder on the very first run), or
- two tweets in a row that you already have, where one of them was at the top of the last run, or
- five different tweets in a row that you already have, or
- N files in a row already in the history (50 unless changed): the safety net.
A bookmark you add again jumps to the top on its own, so it never stops the run early."""
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import fileops
import jobs
import net
import paths
import procenv
import settings

REPO = "mikf/gallery-dl"
HOME = f"https://codeberg.org/{REPO}"
RELEASES_API = f"https://codeberg.org/api/v1/repos/{REPO}/releases/latest"
EXE_NAME = "gallery-dl.exe" if sys.platform == "win32" else "gallery-dl"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
MARK = "@MT@"                          # starts every line the app asks gallery-dl to print
TWITTER_KEY = "{tweet_id}_{num}"       # history key for Twitter, the same for a tweet and its retweets
TWITTER_HOSTS = ("twitter.com", "x.com", "mobile.twitter.com", "fxtwitter.com", "vxtwitter.com")
LOG_RE = re.compile(r"^\[([\w.\-]+)\]\[(\w+)\]\s?(.*)$")
WAIT_RE = re.compile(r"Waiting until (\d{1,2}:\d{2}:\d{2})")
MARKERS_KEPT = 3                       # tweets remembered from the top of each bookmarks run


class GdlError(RuntimeError):
    """Something the person should read: said plainly, with what to do."""


# ----- finding and installing gallery-dl -----
def install_dir():
    return paths.BY_KEY["gdl"].path()


def find_exe():
    """The gallery-dl the app uses: the one chosen in Settings, else the downloaded one. None when neither."""
    own = settings.load().get("gdl_exe")
    if own and Path(own).is_file():
        return Path(own)
    here = install_dir() / EXE_NAME
    return here if here.is_file() else None


_version_cache = {}


def version(exe=None):
    exe = Path(exe or find_exe() or "")
    if not exe.is_file():
        return None
    key = (str(exe), exe.stat().st_mtime)
    if key not in _version_cache:
        try:
            out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30,
                                 creationflags=_NO_WINDOW, env=procenv.clean())
            _version_cache[key] = (out.stdout or out.stderr).strip().splitlines()[0]
        except Exception:
            _version_cache[key] = None
    return _version_cache[key]


def lookup(log=print, progress=None):
    """What would be downloaded: {"tag", "name", "size", "url", "dest"}. Nothing is downloaded yet."""
    if progress:
        progress(0, 0, "Asking Codeberg for the newest gallery-dl")
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": "MediaToolbox",
                                                            "Accept": "application/json"})
    with net.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next((a for a in release.get("assets", []) if a["name"].lower() == "gallery-dl.exe"), None)
    if asset is None:
        raise GdlError(f"The newest gallery-dl release ({release.get('tag_name', '?')}) on Codeberg has no "
                       "gallery-dl.exe. Try again later, or choose your own copy in Settings.")
    info = {"tag": release.get("tag_name", ""), "name": asset["name"], "size": int(asset.get("size") or 0),
            "url": asset["browser_download_url"], "dest": str(install_dir())}
    log(f"Newest gallery-dl: {info['tag']} ({info['size'] / 1048576:.1f} MB).")
    return info


def install(info, log, progress):
    """Download gallery-dl.exe into Models\\gallery-dl (replacing an older one there) and use it."""
    import duplicates_engine as de
    folder = paths.ensure(install_dir())
    dest = folder / EXE_NAME
    new = folder / (EXE_NAME + ".new")
    de.download(info["url"], new, log, progress, f"gallery-dl {info['tag']}")
    progress(0, 0, "Checking the download")
    if not version(new):
        new.unlink(missing_ok=True)
        raise GdlError("The downloaded gallery-dl didn't start. Nothing was changed.")
    os.replace(new, dest)
    settings.save({"gdl_exe": ""})
    log(f"gallery-dl {info['tag']} is in {folder}.")
    return {"summary": f"gallery-dl {info['tag']} installed"}


# ----- history (gallery-dl's download archive) -----
def history_dir():
    return paths.ensure(paths.place("data") / "Downloads" / "history")


def open_history(path):
    con = sqlite3.connect(str(path), timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS archive (entry TEXT PRIMARY KEY) WITHOUT ROWID")
    return con


def history_count(path):
    if not Path(path).is_file():
        return 0
    try:
        con = open_history(path)
        try:
            return con.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def history_add(path, entries):
    """Remember files as downloaded without downloading them."""
    entries = list(entries)
    if not entries:
        return 0
    con = open_history(path)
    try:
        with con:
            con.executemany("INSERT OR IGNORE INTO archive (entry) VALUES (?)", [(e,) for e in entries])
    finally:
        con.close()
    return len(entries)


def twitter_entry(tweet_id, num):
    return f"twitter{tweet_id}_{num}"


# ----- what a download is -----
DEFAULTS = {
    "urls": [], "folder": "", "layout": "flat", "naming": "original", "pattern": "",
    "login": "none", "browser": "firefox", "profile": "", "cookies_file": "",
    "photos": True, "videos": True, "gifs": True, "retweets": False, "replies": True, "quoted": False,
    "after": "", "before": "", "first": 0, "size_min": "", "size_max": "", "rate": "", "wait": 0.0, "retries": 4,
    "history": True, "stop_after": 50, "skip_bookmarks": False, "skip_folders": [],
    "metadata": False, "post_date": False, "zip": False, "use_config": True, "extra": "",
}


def options(src):
    """A download's options with defaults filled in."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (src.get("options") or {}).items() if k in DEFAULTS})
    return out


def is_twitter(url):
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    host = host[4:] if host.startswith("www.") else host
    return host in TWITTER_HOSTS


def site_of(url):
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    host = host[4:] if host.startswith("www.") else host
    return "twitter" if host in TWITTER_HOSTS else host


def _media_filter(o, twitter):
    """A gallery-dl --filter for the kinds of file wanted, or None for everything."""
    if o["photos"] and o["videos"] and o["gifs"]:
        return None
    if twitter:
        kinds = [k for k, on in (("photo", o["photos"]), ("video", o["videos"]), ("animated_gif", o["gifs"])) if on]
        return f"type in {tuple(kinds)!r}" if kinds else "False"
    parts = []
    if o["photos"]:
        parts.append("extension in exts_image")
    if o["videos"]:
        parts.append("(extension in exts_video and extension != 'gif')")
    if o["gifs"]:
        parts.append("extension == 'gif'")
    return " or ".join(parts) if parts else "False"


def build_command(exe, src, history, mode, temp, keep_filter=None):
    """The gallery-dl command for a download. mode: "scan" (list only), "download", "mark" (remember without
    downloading) or "show" (for the command preview: no app-only options)."""
    o = options(src)
    urls = [u.strip() for u in src.get("urls", []) if u.strip()]
    twitter = bool(urls) and all(is_twitter(u) for u in urls)
    cmd = [str(exe)]
    if not o["use_config"]:
        cmd += ["--config-ignore"]
    if mode != "show":
        cmd += ["-o", "output.mode=pipe",
                "-o", 'output.stdout={"encoding": "utf-8", "line_buffering": true}',
                "-o", 'output.stderr={"encoding": "utf-8", "line_buffering": true}']
    # where and what names
    folder = o["folder"] or "."
    cmd += ["-D" if o["layout"] == "flat" else "-d", folder]
    if o["naming"] == "original":
        cmd += ["-f", "/O"]
    elif o["naming"] == "custom" and o["pattern"].strip():
        cmd += ["-f", o["pattern"].strip()]
    # login
    if o["login"] == "browser":
        spec = o["browser"] or "firefox"
        if o["profile"].strip():
            spec += ":" + o["profile"].strip()
        cmd += ["--cookies-from-browser", spec]
    elif o["login"] == "file" and o["cookies_file"].strip():
        cmd += ["--cookies", o["cookies_file"].strip()]
    # Twitter
    if twitter:
        cmd += ["-o", f"retweets={str(o['retweets']).lower()}", "-o", f"replies={str(o['replies']).lower()}",
                "-o", f"quoted={str(o['quoted']).lower()}"]
    # limits
    if o["after"].strip():
        cmd += ["--date-after", o["after"].strip()]
    if o["before"].strip():
        cmd += ["--date-before", o["before"].strip()]
    if int(o["first"] or 0) > 0:
        cmd += ["--range", f"1-{int(o['first'])}"]
    if o["size_min"].strip():
        cmd += ["--filesize-min", o["size_min"].strip()]
    if o["size_max"].strip():
        cmd += ["--filesize-max", o["size_max"].strip()]
    if o["rate"].strip():
        cmd += ["-r", o["rate"].strip()]
    if float(o["wait"] or 0) > 0:
        cmd += ["--sleep-request", f"{float(o['wait']):g}"]
    if int(o["retries"]) != 4:
        cmd += ["-R", str(int(o["retries"]))]
    # history and stopping
    if o["history"] and history:
        cmd += ["--download-archive", str(history)]
        if twitter:
            cmd += ["-o", f"archive-format={TWITTER_KEY}"]
        cmd += ["-o", {"scan": "archive-event=none", "mark": "archive-event=file"}.get(
            mode, "archive-event=file,skip")]
    if o["history"] and int(o["stop_after"] or 0) > 0 and mode in ("scan", "show") or (
            mode == "download" and keep_filter is None and o["history"] and int(o["stop_after"] or 0) > 0):
        cmd += ["-A", str(int(o["stop_after"]))]
    # files kinds, plus (when downloading) exactly the files the scan found
    filters = [f for f in (_media_filter(o, twitter), keep_filter) if f]
    if filters:
        cmd += ["--filter", " and ".join(f"({f})" for f in filters)]
    # extras
    if o["metadata"]:
        cmd += ["--write-metadata"]
    if o["post_date"]:
        cmd += ["--mtime", "date"]
    if o["zip"]:
        cmd += ["--zip"]
    if mode in ("scan", "mark"):
        cmd += ["--no-download"]
    if mode != "show":
        fields = "{filename}.{extension}\t{tweet_id}\t{num}\t{category}\t{author[name]}"
        if mode in ("scan", "mark"):
            cmd += ["--Print", f"prepare-after:{MARK}N\t{fields}", "--Print", f"skip:{MARK}S\t{fields}"]
        else:
            cmd += ["--Print", f"prepare-after:{MARK}P\t{fields}"]
        if temp:
            cmd += ["-o", f"part-directory={temp}"]
    if o["extra"].strip():
        try:
            cmd += shlex.split(o["extra"].strip(), posix=True)
        except ValueError:
            cmd += o["extra"].split()
    cmd += urls
    return cmd


def show_command(src, history=None):
    """The command as you'd type it in a Command Prompt."""
    exe = find_exe() or EXE_NAME
    cmd = build_command(exe, src, history, "show", None)
    cmd[0] = Path(cmd[0]).name
    return subprocess.list2cmdline(cmd) if sys.platform == "win32" else shlex.join(cmd)


# ----- running gallery-dl -----
class Line:
    """One file gallery-dl reported: kind "N" new, "S" skipped, "P" starting to download."""
    __slots__ = ("kind", "name", "tweet", "num", "site", "author")

    def __init__(self, kind, name, tweet, num, site, author):
        self.kind, self.name, self.tweet, self.num, self.site, self.author = kind, name, tweet, num, site, author

    @property
    def key(self):
        return twitter_entry(self.tweet, self.num) if self.tweet else None


def parse_mark(line):
    if not line.startswith(MARK):
        return None
    parts = line[len(MARK):].rstrip("\r\n").split("\t")
    parts += [""] * (6 - len(parts))
    kind, name, tweet, num, site, author = parts[:6]
    tweet = tweet if tweet.isdigit() else ""
    return Line(kind, name, tweet, num if num.isdigit() else "1", site, "" if author == "None" else author)


def explain(lines):
    """Turn gallery-dl's error lines into one sentence the person can act on."""
    text = " ".join(lines).lower()
    if "unsupported url" in text or "no suitable extractor" in text:
        return "gallery-dl doesn't know that address. Check the link, or update gallery-dl in Settings."
    if "authrequired" in text or "401" in text or "login required" in text or "authorization" in text \
            or "not logged in" in text:
        return ("The site says you're not signed in. Sign in in your browser (or pick another login under "
                "Login), then try again.")
    if "cookies" in text and ("firefox" in text or "browser" in text or "decrypt" in text or "database" in text):
        return ("gallery-dl couldn't read your browser's cookies. Firefox works best; Chrome and Edge lock "
                "their cookies on Windows. Close the browser and try again, or use a cookies file.")
    if "429" in text or "rate limit" in text:
        return "The site is limiting requests right now. Wait a while, then run it again."
    if "404" in text or "not found" in text:
        return "That page wasn't found. It may be private or deleted."
    if "abortextraction" in text or "httperror" in text or "unable to" in text:
        return "The site refused part of the request. Updating gallery-dl in Settings often fixes this."
    return ""


class Runner:
    """Runs one gallery-dl command, calling on_line for each file line and on_log for each log line."""

    def __init__(self, cmd, on_line, on_log, on_other=None):
        self.cmd, self.on_line, self.on_log, self.on_other = cmd, on_line, on_log, on_other
        self.proc = None
        self.ended_by_app = False
        self.errors = []

    def run(self):
        env = procenv.clean()
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW, env=env)
        jobs.register_process(self.proc)
        err_thread = threading.Thread(target=self._read_err, daemon=True)
        err_thread.start()
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            mark = parse_mark(line)
            if mark is not None:
                self.on_line(mark)
            elif self.on_other:
                self.on_other(line)
            if self.ended_by_app:
                break
        self.proc.wait()
        err_thread.join(timeout=5)
        return self.proc.returncode

    def _read_err(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            m = LOG_RE.match(line)
            name, level, text = (m.group(1), m.group(2).lower(), m.group(3)) if m else ("", "info", line)
            if level in ("error", "critical") or line.lower().startswith(("traceback", "error")):
                self.errors.append(line)
            self.on_log(name, level, text, line)

    def end(self):
        """Stop gallery-dl because the app has what it needs."""
        self.ended_by_app = True
        jobs.Job._kill(self.proc)


# ----- the stop point for bookmarks -----
class StopRule:
    """Decides when a bookmarks scan has reached what you already have (see the module notes)."""

    def __init__(self, seeds=(), markers=()):
        self.seeds = {s.lower() for s in seeds}
        self.markers = {str(m) for m in markers}
        self.prev_known = None   # the last different tweet seen, when it was one you already have
        self.prev_tweet = None
        self.prev_marker = False
        self.known_run = 0       # different tweets in a row you already have
        self.reason = ""
        self.seed_line = None

    def see(self, line):
        """True when the scan should stop at this file."""
        if line.name.lower() in self.seeds:
            self.reason = f"reached {line.name}, kept from last time"
            self.seed_line = line
            return True
        if not line.tweet or line.tweet == self.prev_tweet:
            return False
        known = line.kind == "S" or line.tweet in self.markers
        marker = line.tweet in self.markers
        self.known_run = self.known_run + 1 if known else 0
        stop = (known and self.prev_known and (marker or self.prev_marker)) or self.known_run >= 5
        self.prev_tweet = line.tweet
        self.prev_known = known
        self.prev_marker = marker
        if stop:
            self.reason = ("reached the top of the last download" if marker or self.prev_marker else
                           "reached tweets you already have")
        return bool(stop)


# ----- the collection check: files you already have somewhere -----
def index_names(folders, progress, log):
    """Lower-case file names in these folders and their subfolders."""
    names = set()
    count = 0
    for folder in folders:
        if not Path(folder).is_dir():
            log(f"Skipping a folder that isn't there: {folder}")
            continue
        for dirpath, _dirs, files in os.walk(folder):
            for f in files:
                names.add(f.lower())
            count += len(files)
            if count % 500 < len(files):
                progress(0, 0, f"Looking through your folders: {count:,} files so far", eta=False)
    log(f"Looked through {count:,} files in {len(folders)} folder(s).")
    return names


# ----- one whole run -----
class Report:
    """What a run did, for the page and the history."""

    def __init__(self):
        self.looked = 0          # files the scan reached
        self.new = []            # Lines found new by the scan
        self.have = 0            # new to this history but already in your folders, so remembered and skipped
        self.skip_run = 0        # files in a row already had, during the scan
        self.done = []           # file paths downloaded
        self.failed = []         # names that failed
        self.stop_reason = ""
        self.top_tweets = []     # the first tweets the scan saw, the next run's stop point
        self.waiting_until = ""


def run(src, history, ctx, log, progress, events):
    """Scan, then download. ctx: {"seeds": [...], "markers": [...], "full": bool, "bookmarks": bool,
    "shared": [extra history files to treat as already had], "confirm": fn(count) -> "all"/"mark"/None}.
    events: an object with started(name), finished(path), status(text) - called from this thread."""
    exe = find_exe()
    if not exe:
        raise GdlError("gallery-dl isn't set up. Choose your gallery-dl.exe or download it in Settings.")
    o = options(src)
    urls = [u.strip() for u in src.get("urls", []) if u.strip()]
    if not urls:
        raise GdlError("Add the address of the page to download.")
    twitter = all(is_twitter(u) for u in urls)
    folder = Path(o["folder"]) if o["folder"] else None
    if folder is None:
        raise GdlError("Choose a folder to put the downloads in.")
    if paths.drive_missing(folder):
        raise GdlError(f"The drive for {folder} isn't there. Plug it in or choose another folder.")
    folder.mkdir(parents=True, exist_ok=True)
    temp = paths.ensure(paths.place("temp") / "gallery-dl")
    rep = Report()

    # 0. other histories to count as already had (both bookmark accounts, for a Twitter profile)
    if twitter and o["history"] and history:
        for other in ctx.get("shared", []):
            if Path(other).is_file() and Path(other) != Path(history):
                _merge_history(other, history)

    # 1. scan
    stop = StopRule(ctx.get("seeds", ()), ctx.get("markers", ()))
    limit = int(o["stop_after"] or 0) if o["history"] else 0
    full = ctx.get("full", False)
    scan_src = dict(src, options=dict(o, stop_after=0 if (full or ctx.get("bookmarks")) else o["stop_after"]))
    seen_tweets = []
    order = []               # every different tweet, in the order the scan reached them
    t0 = time.monotonic()

    def scan_line(line):
        rep.looked += 1
        if line.tweet and line.tweet not in seen_tweets and len(seen_tweets) < MARKERS_KEPT:
            seen_tweets.append(line.tweet)
        if line.tweet and (not order or order[-1] != line.tweet):
            order.append(line.tweet)
        if ctx.get("bookmarks") and not full and stop.see(line):
            rep.stop_reason = stop.reason
            runner.end()
            return
        if line.kind == "N":
            rep.new.append(line)
            rep.skip_run = 0
        else:
            rep.skip_run += 1
            if limit and not full and rep.skip_run >= limit:
                rep.stop_reason = f"{limit} files in a row were already downloaded"
                runner.end()
                return
        what = f"Checking: {rep.looked:,} looked at, {len(rep.new):,} new"
        if limit and not full:
            what += f", {rep.skip_run} in a row already had (stops at {limit})"
        progress(0, 0, what, eta=False)

    def scan_log(name, level, text, line):
        _log_line(log, level, text, line, rep, events)

    progress(0, 0, "Starting gallery-dl", eta=False)
    cmd = build_command(exe, scan_src, history, "scan", temp)
    log("Scan: " + _safe_cmd(cmd))
    runner = Runner(cmd, scan_line, scan_log)
    code = runner.run()
    jobs.check_stop()
    if not runner.ended_by_app and code not in (0, None) and not rep.looked:
        reason = explain(runner.errors)
        raise GdlError(reason or ("gallery-dl stopped with an error: " +
                                  (runner.errors[-1] if runner.errors else f"exit code {code}")))
    if not rep.stop_reason:
        rep.stop_reason = "reached the end of the page"
    rep.top_tweets = seen_tweets
    if stop.seed_line is not None and stop.seed_line.key and o["history"] and history:
        history_add(history, [stop.seed_line.key])  # a file you kept is one you have
    log(f"Scan finished in {fileops.clock(time.monotonic() - t0)}: {rep.looked:,} looked at, "
        f"{len(rep.new):,} new; {rep.stop_reason}.")

    # 2. files you already have in your folders: remember them instead of downloading
    if rep.new and twitter and o["history"] and history and o["skip_folders"]:
        have = index_names(o["skip_folders"], progress, log)
        keep, known = [], []
        for line in rep.new:
            if line.name.lower() in have and line.key:
                known.append(line.key)
            else:
                keep.append(line)
        if known:
            history_add(history, known)
            rep.have = len(known)
            log(f"{len(known):,} of the new files are already in your folders. They're remembered and skipped.")
        rep.new = keep

    if not rep.new:
        return rep

    # 3. many more than usual? (for example a first run without a stop point)
    confirm = ctx.get("confirm")
    if confirm and ctx.get("bookmarks") and len(rep.new) > 300 and not full:
        answer = confirm(len(rep.new))
        if answer == "mark":
            history_add(history, [n.key for n in rep.new if n.key])
            log(f"Remembered {len(rep.new):,} files as downloaded without downloading them.")
            rep.have += len(rep.new)
            rep.new = []
            return rep
        if answer != "all":
            raise jobs.JobStopped()

    # 4. download exactly those files
    total = len(rep.new)
    expected = {}
    for line in rep.new:
        expected.setdefault(line.name.lower(), line)
    keep_filter = None
    if twitter:
        tweets = sorted({int(n.tweet) for n in rep.new if n.tweet})
        after_ids = _after_tweets(order, {n.tweet for n in rep.new})
        keep_filter = f"tweet_id in {set(tweets)!r}"
        if after_ids:
            keep_filter = f"tweet_id in {set(tweets)!r} or (tweet_id in {set(after_ids)!r} and abort())"
    done_names = set()
    failed_names = set()
    t1 = time.monotonic()
    current = [""]

    def eta():
        done = len(rep.done) + len(rep.failed)
        took = time.monotonic() - t1
        if done < 1 or took < 2:
            return False
        return took / done * (total - done)

    def report():
        done = len(rep.done) + len(rep.failed)
        text = f"Downloading {min(done + 1, total):,} of {total:,}"
        if current[0]:
            text += f": {current[0]}"
        if rep.waiting_until:
            text = f"Waiting for the site's rate limit until {rep.waiting_until} ({done:,} of {total:,} done)"
        progress(done, total, text, eta=eta())

    def dl_line(line):
        if line.kind == "P":
            current[0] = line.name
            rep.waiting_until = ""
            events.started(line.name)
            report()

    def dl_other(line):
        if line.startswith("# "):
            return
        path = line.strip()
        name = Path(path).name.lower()
        rep.done.append(path)
        done_names.add(name)
        events.finished(path)
        report()
        if twitter and expected and all(n in done_names or n in failed_names for n in expected):
            _end_later(runner2, 20)  # it normally stops by itself at the next tweet; this is a safety net

    def dl_log(name, level, text, line):
        _log_line(log, level, text, line, rep, events)
        m = re.match(r"Failed to download (.+)$", text)
        if m:
            fname = Path(m.group(1).strip()).name
            rep.failed.append(fname)
            failed_names.add(fname.lower())
            report()
        if WAIT_RE.search(text):
            report()

    dl_src = dict(src, options=dict(o, first=0 if twitter else o["first"]))
    cmd = build_command(exe, dl_src, history, "download", temp, keep_filter=keep_filter)
    log("Download: " + _safe_cmd(cmd))
    report()
    runner2 = Runner(cmd, dl_line, dl_log, dl_other)
    code = runner2.run()
    jobs.check_stop()
    if not rep.done and not rep.failed and code not in (0, None) and not runner2.ended_by_app:
        reason = explain(runner2.errors)
        raise GdlError(reason or ("gallery-dl stopped with an error: " +
                                  (runner2.errors[-1] if runner2.errors else f"exit code {code}")))
    if o["history"] and history:  # make sure every finished file is remembered, however gallery-dl ended
        history_add(history, [expected[n].key for n in done_names if n in expected and expected[n].key])
    missing = [n for n in expected if n not in done_names and n not in failed_names]
    if missing and twitter:
        log(f"{len(missing)} file(s) found by the scan weren't reached (removed from the page meanwhile?).")
    return rep


def _after_tweets(order, new):
    """A few tweets the scan saw just below the last new one: the download stops when it reaches one."""
    last = max((i for i, t in enumerate(order) if t in new), default=-1)
    return [int(t) for t in order[last + 1:last + 6] if t not in new]


def _end_later(runner, seconds):
    def later():
        time.sleep(seconds)
        if runner.proc is not None and runner.proc.poll() is None:
            runner.end()
    if not getattr(runner, "_ending", False):
        runner._ending = True
        threading.Thread(target=later, daemon=True).start()


def _log_line(log, level, text, line, rep, events):
    m = WAIT_RE.search(text)
    if m:
        rep.waiting_until = m.group(1)
        events.status(f"Waiting for the site's rate limit until {m.group(1)}")
    if level in ("error", "critical", "warning"):
        log(f"gallery-dl: {line}")


def _merge_history(src, dst):
    try:
        con = sqlite3.connect(str(src), timeout=30)
        try:
            entries = [r[0] for r in con.execute("SELECT entry FROM archive")]
        finally:
            con.close()
        history_add(dst, entries)
    except sqlite3.Error:
        pass


def _safe_cmd(cmd):
    """The command for the log, with long filters shortened."""
    out = []
    for part in cmd:
        out.append(part if len(part) < 160 else part[:150] + "…")
    return subprocess.list2cmdline(out) if sys.platform == "win32" else shlex.join(out)


def mark_all(src, history, log, progress):
    """Remember every file on the page as downloaded, without downloading anything."""
    exe = find_exe()
    if not exe:
        raise GdlError("gallery-dl isn't set up.")
    o = options(src)
    src = dict(src, options=dict(o, stop_after=0, history=True))
    temp = paths.ensure(paths.place("temp") / "gallery-dl")
    count = [0]

    def line(mark):
        count[0] += 1
        if count[0] % 20 == 0:
            progress(0, 0, f"Remembering files: {count[0]:,} so far", eta=False)

    runner = Runner(build_command(exe, src, history, "mark", temp), line,
                    lambda n, lv, t, raw: log(f"gallery-dl: {raw}") if lv in ("error", "warning") else None)
    code = runner.run()
    jobs.check_stop()
    if code not in (0, None) and not count[0]:
        raise GdlError(explain(runner.errors) or "gallery-dl stopped with an error.")
    return count[0]

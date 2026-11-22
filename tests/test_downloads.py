"""The Downloads tool: where bookmark runs stop, the commands built for gallery-dl, history, the store, and
reading which Twitter account Firefox is signed in to. With gallery-dl installed (and not on Windows, where a
wrapper script can't stand in for the .exe) a full scan-then-download runs against a fake bookmarks site."""
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import browser_account as ba
import gdl_engine as ge
import gdl_store as gs
import settings


def L(kind, tweet, name=None, num="1"):
    return ge.Line(kind, name or f"f{tweet}_{num}.jpg", str(tweet), num, "twitter", "a")


def test_stop_at_a_kept_file():
    rule = ge.StopRule(seeds=["F96_1.jpg"])
    assert not rule.see(L("N", 100))
    assert rule.see(L("S", 96))
    assert "kept" in rule.reason


def test_a_rebookmark_does_not_stop_the_run():
    rule = ge.StopRule(markers=["103", "102", "101"])
    assert not rule.see(L("N", 105))
    assert not rule.see(L("S", 98))      # bookmarked again: it jumped to the top
    assert not rule.see(L("N", 104))
    assert not rule.see(L("S", 103))     # the top of the last run...
    assert rule.see(L("S", 102))         # ...and the next one: stop
    assert "last download" in rule.reason


def test_pictures_of_one_tweet_count_once():
    rule = ge.StopRule(markers=["103"])
    assert not rule.see(L("S", 103, num="1"))
    assert not rule.see(L("S", 103, num="2"))
    assert not rule.see(L("S", 103, num="3"))


def test_five_known_tweets_in_a_row_stop_without_markers():
    rule = ge.StopRule()
    results = [rule.see(L("S", t)) for t in (90, 89, 88, 87, 86)]
    assert results == [False, False, False, False, True]


def test_command_for_a_bookmarks_scan(places):
    src = {"kind": "bookmarks", "urls": [gs.BOOKMARKS_URL],
           "options": {"folder": "C:/dl/new", "login": "browser", "browser": "firefox", "naming": "original"}}
    cmd = ge.build_command("gallery-dl.exe", src, "h.sqlite3", "scan", "tmp")
    assert cmd[-1] == gs.BOOKMARKS_URL
    assert ["-D", "C:/dl/new"] == cmd[cmd.index("-D"):cmd.index("-D") + 2]
    assert "--no-download" in cmd and "--cookies-from-browser" in cmd
    assert f"archive-format={ge.TWITTER_KEY}" in cmd and "archive-event=none" in cmd
    assert any(c.startswith("prepare-after:" + ge.MARK) for c in cmd)


def test_command_download_keeps_just_the_new_files(places):
    src = {"kind": "recent", "urls": ["https://x.com/artist/media"],
           "options": {"folder": "D:/x", "videos": False, "first": 10}}
    cmd = ge.build_command("gallery-dl.exe", src, "h.sqlite3", "download", "tmp", keep_filter="tweet_id in {1, 2}")
    f = cmd[cmd.index("--filter") + 1]
    assert "tweet_id in {1, 2}" in f and "'photo'" in f and "'video'" not in f
    assert "archive-event=file,skip" in cmd and "--no-download" not in cmd
    assert "-A" not in cmd  # the filter decides; stopping early could miss some
    shown = ge.show_command(src)
    assert "output.mode" not in shown and "--range" in shown


def test_parse_mark():
    line = ge.parse_mark(f"{ge.MARK}N\tabc.jpg\t123\t2\ttwitter\tSomeone")
    assert (line.kind, line.name, line.tweet, line.num, line.key) == ("N", "abc.jpg", "123", "2", "twitter123_2")
    assert ge.parse_mark("D:/x/abc.jpg") is None
    other = ge.parse_mark(f"{ge.MARK}N\tpic.png\tNone\t1\tpixiv\tNone")
    assert other.tweet == "" and other.key is None and other.author == ""


def test_history_add_and_count(places, tmp_path):
    h = tmp_path / "h.sqlite3"
    assert ge.history_count(h) == 0
    ge.history_add(h, ["twitter1_1", "twitter2_1", "twitter1_1"])
    assert ge.history_count(h) == 2
    con = sqlite3.connect(h)  # gallery-dl's own archive layout
    assert con.execute("SELECT entry FROM archive ORDER BY entry").fetchall() == [("twitter1_1",), ("twitter2_1",)]
    con.close()


def test_store_round_trip(places):
    data = gs.load()
    assert [data["accounts"][k]["name"] for k, _n in gs.ACCOUNTS] == ["Main account", "Second account"]
    assert gs.history_file(data["accounts"]["main"]) == gs.history_file(data["accounts"]["second"])
    src = gs.new_download(["https://x.com/a/media"], {"folder": "D:/a"})
    gs.put(src)
    assert gs.load()["recent"][0]["id"] == src["id"]
    src["kind"], src["name"] = "saved", "Artist A"
    gs.put(src)
    data = gs.load()
    assert not data["recent"] and data["saved"][0]["name"] == "Artist A"
    assert gs.history_file(src) != gs.history_file(data["accounts"]["main"])
    twin = gs.new_download(["https://x.com/a/media"], {"folder": "D:/a"})
    assert gs.same_setup(src, twin)


def test_seeds_only_from_a_chosen_folder(tmp_path):
    assert gs.seeds_from_folder("") == []
    (tmp_path / "a.jpg").write_text("x")
    (tmp_path / "desktop.ini").write_text("x")
    assert gs.seeds_from_folder(str(tmp_path)) == ["a.jpg"]


def test_firefox_account(tmp_path, monkeypatch):
    prof = tmp_path / "Profiles" / "abc.default-release"
    prof.mkdir(parents=True)
    (tmp_path / "profiles.ini").write_text("[Profile0]\nName=default-release\nIsRelative=1\n"
                                           "Path=Profiles/abc.default-release\nDefault=1\n")
    con = sqlite3.connect(prof / "cookies.sqlite")
    con.execute("CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, lastAccessed INTEGER)")
    con.execute("INSERT INTO moz_cookies VALUES ('twid', 'u%3D1234567890', '.x.com', 5)")
    con.commit()
    con.close()
    monkeypatch.setattr(ba, "firefox_dir", lambda: tmp_path)
    assert ba.twitter_user_id() == "1234567890"


# ----- a whole run against a fake bookmarks site -----
FAKE = '''
from gallery_dl.extractor.common import Extractor, Message
import os
class FaketwExtractor(Extractor):
    category = "twitter"
    subcategory = "bookmark"
    pattern = r"https://x\\.com/i/bookmarks"
    archive_fmt = "{tweet_id}_{retweet_id}_{num}"
    filename_fmt = "{filename}.{extension}"
    directory_fmt = ("twitter",)
    def items(self):
        base = os.environ["FAKE_BASE"]
        for item in open(os.environ["FAKE_TW"]).read().split():
            tid, num, name = item.split(":")
            stem, ext = name.rsplit(".", 1)
            kw = {"tweet_id": int(tid), "retweet_id": 0, "num": int(num), "filename": stem, "extension": ext,
                  "type": "photo", "author": {"name": "a"}}
            yield Message.Directory, "", kw
            yield Message.Url, base + name, kw
'''


class _Events:
    def started(self, name):
        pass

    def finished(self, path):
        pass

    def status(self, text):
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="needs a wrapper script in place of gallery-dl.exe")
def test_bookmarks_run_end_to_end(places, tmp_path, monkeypatch):
    pytest.importorskip("gallery_dl")
    www, mods, dl = tmp_path / "www", tmp_path / "mods", tmp_path / "dl"
    for d in (www, mods, dl):
        d.mkdir()
    (mods / "faketw.py").write_text(FAKE)
    (tmp_path / "conf.json").write_text('{"extractor": {"module-sources": ["%s"]}}' % mods)
    wrapper = tmp_path / "gdl"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} -m gallery_dl -c {tmp_path / 'conf.json'} \"$@\"\n")
    wrapper.chmod(0o755)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(www)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("FAKE_BASE", f"http://127.0.0.1:{server.server_port}/")
    monkeypatch.setenv("FAKE_TW", str(tmp_path / "tw.txt"))
    settings.save({"gdl_exe": str(wrapper)})

    def bookmarks(tweets):
        items = [f"{t}:1:f{t}_1.jpg" for t in tweets]
        for it in items:
            (www / it.split(":")[2]).write_text("x")
        (tmp_path / "tw.txt").write_text(" ".join(items))

    src = {"id": "main", "kind": "bookmarks", "urls": [gs.BOOKMARKS_URL], "options": {"folder": str(dl)}}
    hist = gs.history_file(src)
    (dl / "f96_1.jpg").write_text("kept")
    try:
        bookmarks(range(103, 90, -1))
        rep = ge.run(src, hist, {"bookmarks": True, "seeds": gs.seeds_from_folder(dl)}, print,
                     lambda *a, **k: None, _Events())
        assert sorted(Path(p).name for p in rep.done) == [f"f{t}_1.jpg" for t in (100, 101, 102, 103, 97, 98, 99)]
        assert rep.top_tweets == ["103", "102", "101"]
        for f in dl.iterdir():   # sorted away: history still knows them
            f.unlink()
        bookmarks([105, 98, 104] + list(range(103, 90, -1)))
        rep = ge.run(src, hist, {"bookmarks": True, "markers": rep.top_tweets}, print, lambda *a, **k: None,
                     _Events())
        assert sorted(Path(p).name for p in rep.done) == ["f104_1.jpg", "f105_1.jpg"]
        assert "last download" in rep.stop_reason
    finally:
        server.shutdown()

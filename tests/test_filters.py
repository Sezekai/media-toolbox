"""Collection filter rules and the silent scan's length."""
import shutil
import subprocess
import time
import types

import pytest

import collection as col
import silent_videos


def _coll():
    c = types.SimpleNamespace()
    c.filter_fields = {"name": ("Name", "text", lambda i: i["name"]), "size": ("Size", "size", None),
                       "duration": ("Length", "time", None), "mtime": ("Modified", "age", None)}
    return c


def test_rules():
    c = _coll()
    item = {"name": "Clip.mp4", "size": 3 * 1024 ** 2, "duration": 8.0, "mtime": time.time() - 3 * 86400}
    assert col.Rule(c, "size", "lt", "5", "MB").test(item)
    assert not col.Rule(c, "size", "gt", "5", "MB").test(item)
    assert col.Rule(c, "duration", "lt", "10", "seconds").test(item)
    assert not col.Rule(c, "duration", "gt", "1", "minutes").test(item)
    assert col.Rule(c, "mtime", "lt", "1", "weeks").test(item)
    assert col.Rule(c, "name", "has", "clip").test(item)
    assert col.Rule(c, "name", "not", "zzz").test(item)
    assert not col.Rule(c, "duration", "lt", "", "seconds").complete()   # half-typed: ignored
    assert not col.Rule(c, "duration", "lt", "10", "seconds").test(dict(item, duration=None))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_silent_scan_reads_length(tmp_path):
    out = tmp_path / "quiet.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=10",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    silent, reason, duration = silent_videos.check_video(out, False, -50)
    assert silent and reason == "No audio track" and abs(duration - 3) < 0.2

import shutil
import subprocess

import pytest

import video_covers as vc

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg on PATH")


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-f",
                    "lavfi", "-i", "sine", "-t", "2", "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.mark.parametrize("ext", [".mp4", ".mkv"])
def test_set_and_remove_cover(clip, tmp_path, monkeypatch, ext):
    monkeypatch.setattr(vc.fileops, "recycle", lambda p: p.unlink())  # no Recycle Bin in tests
    path = clip
    if ext != ".mp4":
        path = tmp_path / ("clip" + ext)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(clip), "-c", "copy", str(path)], check=True)
    assert not vc.has_cover(path)
    done, failed = vc.apply([(str(path), ("percent", 50))], log=lambda *_: None)
    assert (done, failed) == (1, 0) and vc.has_cover(path) and vc.read_cover(path) is not None
    done, failed = vc.apply([(str(path), ("remove", None))], log=lambda *_: None)
    assert (done, failed) == (1, 0) and not vc.has_cover(path)


def test_unsupported_kind(tmp_path):
    assert not vc.supported(tmp_path / "x.webm")
    done, failed = vc.apply([(str(tmp_path / "x.avi"), ("percent", 10))], log=lambda *_: None)
    assert (done, failed) == (0, 1)

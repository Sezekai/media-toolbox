"""Compare videos: finding comparisons, lining copies up, best picture and sound, combining."""
import shutil
import subprocess
from pathlib import Path

import pytest

import compare_engine as ce

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def test_find_comparisons(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for name in ("a/1.mp4", "a/2.mkv", "b/1.mp4", "top1.mp4", "top2.mp4", "a/notes.txt"):
        (tmp_path / name).write_text("x")
    found = {Path(g["folder"]).name: len(g["videos"]) for g in ce.find_comparisons(tmp_path)}
    assert found == {tmp_path.name: 2, "a": 2}


def test_best_picture_and_sound():
    pic = {"video": {"width": 1920, "height": 1080, "fps": 30, "depth": 8, "bitrate": 8e6}, "audio": None,
           "size": 10, "bitrate": 8e6}
    snd = {"video": {"width": 640, "height": 360, "fps": 30, "depth": 8, "bitrate": 1e6},
           "audio": {"codec": "aac", "channels": 2, "rate": 48000, "bitrate": 192000}, "size": 5, "bitrate": 1.2e6}
    assert ce.best([snd, pic]) == (1, 0)


@needs_ffmpeg
def test_line_up_and_combine(tmp_path):
    src = tmp_path / "src.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "14",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", src)
    pic = tmp_path / "pic.mp4"
    _ff("-i", src, "-an", "-vf", "scale=640:360", "-c:v", "libx264", "-preset", "ultrafast", pic)
    snd = tmp_path / "snd.mp4"
    _ff("-ss", "3", "-i", src, "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", snd)
    infos = [ce.probe(pic), ce.probe(snd)]
    offsets, sure = ce.align(infos)
    assert offsets[0] == 0 and abs(offsets[1] - 3.0) < 0.1 and sure[1] > 0.5
    assert ce.best(infos) == (0, 1)
    out = tmp_path / "out.mp4"
    result = ce.combine(infos[0], infos[1], offsets[0], offsets[1], out, print)
    assert result["video"]["width"] == 640 and result["audio"]
    copy = subprocess.run(["ffmpeg", "-v", "error", "-i", str(pic), "-map", "0:v", "-c", "copy", "-f", "h264", "-"],
                          capture_output=True).stdout
    again = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-map", "0:v", "-c", "copy", "-f", "h264", "-"],
                           capture_output=True).stdout
    assert copy == again  # the picture is copied, never re-encoded

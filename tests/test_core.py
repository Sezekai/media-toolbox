import json
from pathlib import Path

import appearance
import duplicates_engine as de
import fileops
import movelog
import paths
import settings


def test_places_follow_root(places):
    assert paths.root() == places / "root"
    assert paths.data_dir() == places / "data"
    assert paths.BY_KEY["engine"].path() == places / "root" / "Models" / "vdf-cli"
    assert paths.BY_KEY["thumbs"].path() == places / "root" / "Cache" / "thumbs"


def test_storage_override(places):
    settings.save({"storage": {"fingerprints": str(places / "elsewhere")}})
    assert paths.BY_KEY["fingerprints"].path() == places / "elsewhere"


def test_settings_round_trip():
    settings.save({"a": 1})
    settings.save({"b": 2})
    assert settings.load()["a"] == 1 and settings.load()["b"] == 2
    settings.reset(keep=("b",))
    assert "a" not in settings.load() and settings.load()["b"] == 2


def test_unique_path_numbers_from_two(tmp_path):
    (tmp_path / "clip.gif").write_text("x")
    assert fileops.unique_path(tmp_path, "clip.gif").name == "clip (2).gif"
    (tmp_path / "clip (2).gif").write_text("x")
    assert fileops.unique_path(tmp_path, "clip.gif").name == "clip (3).gif"


def test_move_and_undo(tmp_path):
    src = tmp_path / "a" / "v.mp4"
    src.parent.mkdir()
    src.write_text("video")
    dst = fileops.move_file(src, tmp_path / "b")
    entry = movelog.record("Test", "Moved 1", [("move", src, dst)])
    assert not src.exists() and dst.exists()
    done, problems = movelog.undo(entry["id"])
    assert done == 1 and not problems and src.exists() and not dst.exists()
    assert movelog.entries()[0]["undone"]


def test_undo_explains_missing_file(tmp_path):
    src, dst = tmp_path / "x.mp4", tmp_path / "gone.mp4"
    entry = movelog.record("Test", "Moved 1", [("move", src, dst)])
    done, problems = movelog.undo(entry["id"])
    assert done == 0 and "outside the app" in problems[0]


def test_clock_and_sizes():
    assert fileops.clock(65) == "1:05"
    assert fileops.clock(3725) == "1:02:05"
    assert fileops.human_size(1536).startswith("1.5")


def test_default_theme_and_contrast():
    t = appearance.normalize(appearance.DEFAULT_THEME)
    assert t["font"]["family"] == "Inter"
    assert appearance.on_accent_contrast(t) >= 4.5
    wild = appearance.normalize({"font": {"size": 99}, "corners": {"control": -5}})
    assert 11 <= wild["font"]["size"] <= 16 and wild["corners"]["control"] >= 0


def test_theme_file_round_trip(tmp_path):
    path = tmp_path / "x.theme.json"
    appearance.write_theme_file(appearance.CLASSIC_THEME, path)
    back = appearance.read_theme_file(path)
    assert appearance.same_look(back, appearance.CLASSIC_THEME)


def test_parse_progress_uses_stage_counts():
    line = "[ 50%] 120/240  ETA 00:01:05  D:\\v\\a.mp4 (Hashing 3/10)    "
    done, total, stage, eta = de.parse_progress(line)
    assert (done, total, stage, eta) == (3, 10, "Hashing", 65)


def test_plan_moves_copies_files_in_two_groups(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("a.mp4", "b.mp4", "c.mp4"))
    item = lambda p, best=False: {"path": p, "best": best, "pixels": 1, "bitrate": 1, "size": 1}
    groups = [{"key": "g1", "items": [item(a, True), item(b)]}, {"key": "g2", "items": [item(a, True), item(c)]}]
    ops = de.plan_moves(groups, {"g1"}, [], str(tmp_path / "out"))
    by_src = {Path(o["src"]).name: o for o in ops}
    assert by_src["a.mp4"]["copy"] is True and by_src["b.mp4"]["copy"] is False
    assert "Group 1 - a" in by_src["b.mp4"]["dst_dir"]


def test_build_command_gpu_flag():
    cfg = de.Options(recursive=False, percent=95, audio=False, audio_ratio=0.1, audio_similarity=0.8, visual=False,
                     visual_hit=89)
    cmd = de.build_command("vdf", ["X"], cfg, "db", "out.json", gpu=True)
    assert "--hardware-accel" in cmd and cmd[cmd.index("--hardware-accel") + 1] == "cuda"
    assert "--no-subdirs" in cmd and "--checkpoint-interval" in cmd

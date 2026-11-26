"""Compare videos: the work behind the Compare screen.

- Comparisons: every folder (the chosen one and any below it) with two or more videos directly inside.
- Details: resolution, frame rate, codecs, bitrates, size, length and sound, from ffprobe.
- Best picture and best sound, by score.
- Lining up: copies of the same clip can start and end at different points. Each video is sampled as a tiny
  greyscale film (5 frames a second); the brightness of a 3×3 grid over time is cross-correlated against the
  longest video to find where each one starts, then refined to a frame at 25 frames a second. The result is an
  offset per video: where it starts on a shared timeline.
- Combining: the best picture with another copy's sound, lined up. The picture is copied as it is (never
  re-encoded); the sound is copied too when the container takes it, otherwise it becomes AAC 256 kb/s.

Nothing here deletes anything: the Compare screen sends unwanted copies to the Recycle Bin."""
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import fileops
import paths
from media_utils import VIDEO_EXTENSIONS

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
SAMPLE_FPS = 5           # the coarse line-up
FINE_FPS = 25            # the refinement
GRID = 3                 # brightness of a 3×3 grid per frame
MAX_SAMPLE_S = 900       # longest stretch sampled per video (15 minutes)


def _run(args, timeout=None):
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)


# ----- finding comparisons -----
def videos_in(folder):
    try:
        return sorted((p for p in Path(folder).iterdir()
                       if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and not p.name.startswith(".")),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def find_comparisons(root):
    """[{"folder", "videos": [paths]}] for every folder from root down with 2+ videos directly in it."""
    found = []
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        vids = videos_in(dirpath)
        if len(vids) >= 2:
            found.append({"folder": str(Path(dirpath)), "videos": [str(v) for v in vids]})
    return found


# ----- details -----
def _ratio(text):
    try:
        a, _, b = str(text).partition("/")
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path):
    """What a video is: picture, sound, size and length."""
    out = _run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration,size,bit_rate:stream=index,codec_type,codec_name,profile,width,height,"
                "avg_frame_rate,r_frame_rate,bit_rate,pix_fmt,bits_per_raw_sample,channels,channel_layout,"
                "sample_rate:stream_disposition=attached_pic", "-of", "json", str(path)], timeout=60)
    data = json.loads(out.stdout or b"{}")
    fmt = data.get("format", {})
    info = {"path": str(path), "name": Path(path).name, "size": int(fmt.get("size") or 0) or _size(path),
            "duration": float(fmt.get("duration") or 0), "bitrate": int(fmt.get("bit_rate") or 0),
            "video": None, "audio": None}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic") \
                and info["video"] is None:
            fps = _ratio(s.get("avg_frame_rate")) or _ratio(s.get("r_frame_rate"))
            info["video"] = {"codec": s.get("codec_name", ""), "width": int(s.get("width") or 0),
                             "height": int(s.get("height") or 0), "fps": round(fps, 3),
                             "bitrate": int(s.get("bit_rate") or 0), "pix_fmt": s.get("pix_fmt", ""),
                             "depth": int(s.get("bits_per_raw_sample") or 0) or (10 if "10" in s.get("pix_fmt", "")
                                                                                 else 8)}
        elif s.get("codec_type") == "audio" and info["audio"] is None:
            info["audio"] = {"codec": s.get("codec_name", ""), "channels": int(s.get("channels") or 0),
                             "layout": s.get("channel_layout", ""), "rate": int(s.get("sample_rate") or 0),
                             "bitrate": int(s.get("bit_rate") or 0), "index": int(s.get("index") or 0)}
    v = info["video"]
    if v and not v["bitrate"] and info["bitrate"]:
        v["bitrate"] = max(0, info["bitrate"] - ((info["audio"] or {}).get("bitrate") or 0))
        v["estimated"] = True
    return info


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def video_score(info):
    """Higher is a better picture: pixels first, then bitrate (per pixel), frame rate, bit depth, size."""
    v = info.get("video")
    if not v:
        return (0, 0, 0, 0, 0)
    pixels = v["width"] * v["height"]
    return (pixels, round(min(v["fps"], 120)), v["depth"], v["bitrate"], info["size"])


def audio_score(info):
    """Higher is better sound: having any, channels, sample rate, bitrate, lossless codecs first."""
    a = info.get("audio")
    if not a:
        return (0, 0, 0, 0, 0)
    lossless = 1 if a["codec"] in ("flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "truehd") else 0
    rate = a["bitrate"] or (info["bitrate"] - ((info.get("video") or {}).get("bitrate") or 0)) // 10
    return (1, min(a["channels"], 8), lossless, a["rate"], rate)


def best(infos):
    """(index of the best picture, index of the best sound or None)."""
    bv = max(range(len(infos)), key=lambda i: video_score(infos[i]))
    with_sound = [i for i in range(len(infos)) if infos[i].get("audio")]
    if not with_sound:
        return bv, None
    top = max(audio_score(infos[i]) for i in with_sound)
    tied = [i for i in with_sound if audio_score(infos[i]) == top]
    return bv, (bv if bv in tied else tied[0])


def describe(info):
    """Lines of details for a tile, shortest first."""
    v, a = info.get("video"), info.get("audio")
    lines = []
    if v:
        lines.append(f"{v['width']}×{v['height']} · {v['fps']:g} fps · {v['codec']}"
                     + (f" · {v['depth']}-bit" if v["depth"] > 8 else ""))
        lines.append(f"Picture {kbps(v['bitrate'])}{' (est.)' if v.get('estimated') else ''} · "
                     f"{fileops.human_size(info['size'])} · {fileops.clock(info['duration'])}")
    else:
        lines.append(f"No picture · {fileops.human_size(info['size'])} · {fileops.clock(info['duration'])}")
    if a:
        ch = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(a["channels"], f"{a['channels']} ch")
        lines.append(f"Sound {a['codec']} {ch} · {a['rate'] / 1000:g} kHz" + (f" · {kbps(a['bitrate'])}"
                                                                           if a["bitrate"] else ""))
    else:
        lines.append("No sound")
    return lines


def kbps(bps):
    if not bps:
        return "bitrate unknown"
    return f"{bps / 1_000_000:.1f} Mb/s" if bps >= 1_000_000 else f"{bps / 1000:.0f} kb/s"


# ----- lining up -----
def _film(path, fps, start=0.0, length=None, w=48, h=27):
    """Tiny greyscale frames as a numpy array (frames, h, w)."""
    import numpy as np
    args = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path), "-an", "-sn", "-t", f"{length if length else MAX_SAMPLE_S:.3f}",
             "-vf", f"fps={fps},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    out = _run(args, timeout=600).stdout
    frames = len(out) // (w * h)
    return np.frombuffer(out[:frames * w * h], dtype=np.uint8).reshape(frames, h, w).astype(np.float32)


def _signals(film):
    """Brightness of a 3×3 grid over time, as changes from frame to frame, normalised: (channels, time)."""
    import numpy as np
    if len(film) < 3:
        return np.zeros((GRID * GRID, max(0, len(film) - 1)), dtype=np.float32)
    t, h, w = film.shape
    cells = film[:, :h // GRID * GRID, :w // GRID * GRID].reshape(t, GRID, h // GRID, GRID, w // GRID)
    means = cells.mean(axis=(2, 4)).reshape(t, GRID * GRID).T          # (9, t)
    diff = np.diff(means, axis=1)
    diff -= diff.mean(axis=1, keepdims=True)
    diff /= (diff.std(axis=1, keepdims=True) + 1e-6)
    return diff


def _xcorr(ref, other):
    """For each lag (other's start in ref's frames, from -(len(other)-1) to len(ref)-1), the mean correlation
    over the overlap, summed across channels. Lags with too little overlap score -inf."""
    import numpy as np
    n, m = ref.shape[1], other.shape[1]
    size = 1 << int(math.ceil(math.log2(n + m)))
    total = np.zeros(n + m - 1)
    for a, b in zip(ref, other):
        fa = np.fft.rfft(a, size)
        fb = np.fft.rfft(b[::-1], size)
        total += np.fft.irfft(fa * fb, size)[:n + m - 1]
    lags = np.arange(n + m - 1) - (m - 1)          # other's frame 0 sits at ref frame `lag`
    overlap = np.minimum(n, lags + m) - np.maximum(0, lags)
    need = max(4, int(min(n, m) * 0.3))
    score = np.where(overlap >= need, total / np.maximum(overlap, 1) / ref.shape[0], -np.inf)
    return lags, score


def align(infos, progress=None):
    """Offsets (seconds) on a shared timeline: where each video starts. The longest video starts at 0 and
    the others are placed where they match it best. Also returns how sure each match is (0–1)."""
    import numpy as np
    n = len(infos)
    ref = max(range(n), key=lambda i: infos[i]["duration"])
    films = []
    for k, info in enumerate(infos):
        if progress:
            progress(k, n + 1, f"Reading {info['name']} to line it up")
        films.append(_signals(_film(info["path"], SAMPLE_FPS)) if info.get("video") else None)
    offsets, sure = [0.0] * n, [1.0] * n
    for i in range(n):
        if i == ref or films[i] is None or films[ref] is None or films[i].shape[1] < 4 or films[ref].shape[1] < 4:
            continue
        lags, score = _xcorr(films[ref], films[i])
        k = int(np.argmax(score))
        if not np.isfinite(score[k]):
            sure[i] = 0.0
            continue
        coarse = float(lags[k] / SAMPLE_FPS)
        sure[i] = float(max(0.0, min(1.0, score[k])))
        offsets[i] = coarse
    if progress:
        progress(n, n + 1, "Fine-tuning to the frame")
    for i in range(n):  # refine to a frame, on a short stretch both videos share
        if i == ref or sure[i] <= 0.05 or films[i] is None:
            continue
        try:
            offsets[i] = _refine(infos[ref], infos[i], offsets[i])
        except Exception:
            pass
    low = min(offsets)
    return [round(float(o - low), 3) for o in offsets], [round(float(s), 3) for s in sure]


def _refine(ref_info, info, coarse):
    """Search ±0.6 s around the coarse offset at 25 frames a second, on up to 12 s both videos share."""
    import numpy as np
    start_other = max(0.0, 1.0)                     # a second in, past any fade
    span = min(12.0, info["duration"] - start_other - 0.5, ref_info["duration"] - (coarse + start_other) - 1.0)
    if span < 2:
        return coarse
    ref_start = max(0.0, coarse + start_other - 0.6)
    a = _signals(_film(ref_info["path"], FINE_FPS, ref_start, span + 1.2))
    b = _signals(_film(info["path"], FINE_FPS, start_other, span))
    if a.shape[1] < 10 or b.shape[1] < 10:
        return coarse
    lags, score = _xcorr(a, b)
    window = (lags >= 0) & (lags <= int(1.2 * FINE_FPS))
    if not window.any():
        return coarse
    k = int(np.argmax(np.where(window, score, -np.inf)))
    return float(ref_start + lags[k] / FINE_FPS - start_other)


# ----- cache: details and line-ups are remembered until a file changes -----
def _cache_path():
    return paths.ensure(paths.place("data")) / "compare_cache.json"


def _key(paths_):
    parts = []
    for p in sorted(paths_):
        try:
            st = Path(p).stat()
            parts.append(f"{p}|{st.st_size}|{int(st.st_mtime)}")
        except OSError:
            parts.append(f"{p}|gone")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def prepare(videos, log, progress):
    """Details, best picture and sound, and the line-up for one comparison (from the cache when unchanged)."""
    key = _key(videos)
    cache = fileops.read_json(_cache_path(), {})
    hit = cache.get(key)
    if hit and [i["path"] for i in hit["infos"]] == list(videos):
        return hit
    infos = []
    for k, v in enumerate(videos):
        progress(k, len(videos) * 2 + 1, f"Reading the details of {Path(v).name}")
        try:
            infos.append(probe(v))
        except Exception as exc:
            log(f"Couldn't read {Path(v).name}: {exc}")
            infos.append({"path": v, "name": Path(v).name, "size": _size(v), "duration": 0, "bitrate": 0,
                          "video": None, "audio": None})
    playable = [i for i in infos if i.get("video")]
    if len(playable) >= 2:
        offsets, sure = align(infos, lambda d, t, w: progress(len(videos) + d, len(videos) * 2 + 1, w))
    else:
        offsets, sure = [0.0] * len(infos), [0.0] * len(infos)
    bv, ba = best(infos)
    result = {"infos": infos, "offsets": offsets, "sure": sure, "best_video": bv, "best_audio": ba}
    cache[key] = result
    if len(cache) > 400:  # keep the newest few hundred
        for old in list(cache)[:len(cache) - 400]:
            cache.pop(old, None)
    try:
        fileops.write_json(_cache_path(), cache)
    except OSError:
        pass
    return result


# ----- combining the best picture with the best sound -----
MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "opus", "alac", "flac", "mp2"}
MKV_AUDIO = None  # Matroska takes any sound


def combine(video_info, audio_info, video_offset, audio_offset, out_path, log):
    """Write out_path: video_info's picture (copied, never re-encoded) with audio_info's sound, lined up.
    Offsets are where each starts on the shared timeline."""
    ext = Path(out_path).suffix.lower()
    a = audio_info["audio"]
    shift = video_offset - audio_offset   # where the picture's 0:00 falls in the sound's own time
    args = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(video_info["path"])]
    if shift > 0.001:
        args += ["-ss", f"{shift:.3f}", "-i", str(audio_info["path"])]
    elif shift < -0.001:
        args += ["-itsoffset", f"{-shift:.3f}", "-i", str(audio_info["path"])]
    else:
        args += ["-i", str(audio_info["path"])]
    args += ["-map", "0:v:0", "-map", "1:a:0", "-map", "0:s?", "-c:v", "copy", "-c:s", "copy",
             "-map_metadata", "0", "-t", f"{video_info['duration']:.3f}"]
    keep_sound = ext in (".mkv", ".webm") and (ext != ".webm" or a["codec"] in ("opus", "vorbis")) \
        or ext in (".mp4", ".m4v", ".mov") and a["codec"] in MP4_AUDIO
    if keep_sound:
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", "aac", "-b:a", "256k"]
        log(f"The sound ({a['codec']}) can't go into a {ext} file as it is, so it becomes AAC 256 kb/s. "
            "The picture is copied unchanged.")
    if ext in (".mp4", ".m4v", ".mov"):
        args += ["-movflags", "+faststart"]
    args += [str(out_path)]
    res = _run(args, timeout=3600)
    if res.returncode != 0 or not Path(out_path).is_file():
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError((res.stderr or b"").decode("utf-8", "replace").strip()[-400:] or "ffmpeg failed")
    check = probe(out_path)
    if not check.get("video") or not check.get("audio"):
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError("the combined file didn't come out with both picture and sound")
    return check

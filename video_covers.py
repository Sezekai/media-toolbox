"""Set the picture Windows shows for a video (its thumbnail in File Explorer).

Windows uses a video's embedded cover picture when it has one, and a frame from the video when it doesn't.
So a new thumbnail is a cover picture added to the file. The video and sound are copied, not re-encoded, so
nothing about them changes. The original file goes to the Recycle Bin, so it can be restored.

- MP4 and M4V: the cover is an "attached picture", which File Explorer shows.
- MKV: the cover is a cover attachment. File Explorer only shows it with a thumbnail add-on such as Icaros;
  players and media libraries use it.
- Other kinds (MOV, WebM, AVI, WMV, FLV, MPG, 3GP) can't carry a cover Windows reads.
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

import fileops
from media_utils import noop, probe_video, run

MP4_LIKE = {".mp4", ".m4v"}
SUPPORTED = MP4_LIKE | {".mkv"}
MAX_SIDE = 1280  # covers bigger than this are scaled down (Explorer never shows them bigger)


def supported(path):
    return Path(path).suffix.lower() in SUPPORTED


def why_not(path):
    ext = Path(path).suffix.lower() or "this kind of file"
    return f"{ext} files can't hold a picture Windows reads. MP4, M4V and MKV can."


def _streams(path):
    """[(index, codec_type, is_attached_pic, codec_name)] for every stream."""
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name:"
               "stream_disposition=attached_pic", "-of", "csv=p=0", str(path)]).stdout or ""
    streams = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            # csv order: index, codec_name, codec_type, attached_pic
            idx, name, kind = int(parts[0]), parts[1], parts[2]
            pic = len(parts) > 3 and parts[3] == "1"
            streams.append((idx, kind, pic, name))
    return streams


def _attachments(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "t", "-show_entries", "stream=index:stream_tags=filename",
               "-of", "csv=p=0", str(path)]).stdout or ""
    found = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            found.append((int(parts[0]), parts[1]))
    return found


def _pic_names(path):
    """{stream index: file name} for attached pictures (MKV image attachments are read as these)."""
    out = run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
               "stream=index:stream_disposition=attached_pic:stream_tags=filename", "-of", "csv=p=0",
               str(path)]).stdout or ""
    names = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] == "1":
            names[int(parts[0])] = parts[2] if len(parts) > 2 else ""
    return names


def _cover_streams(path):
    """Stream indexes of the cover picture(s). In MKV only pictures named cover… (or unnamed) count."""
    names = _pic_names(path)
    if Path(path).suffix.lower() == ".mkv":
        found = [i for i, n in names.items() if not n or n.lower().startswith("cover")]
        found += [i for i, n in _attachments(path) if n.lower().startswith("cover") and i not in found]
        return found
    return list(names)


def _other_pictures(path):
    """MKV pictures that aren't the cover (FFmpeg can't copy those back as attachments)."""
    if Path(path).suffix.lower() != ".mkv":
        return []
    covers = set(_cover_streams(path))
    return [i for i in _pic_names(path) if i not in covers]


def has_cover(path):
    """True when the video already has a cover picture."""
    return bool(_cover_streams(path))


def read_cover(path, max_side=480):
    """The video's cover picture as a PIL image, or None."""
    pics = [i for i, _k, pic, _n in _streams(path) if pic]
    if not pics:
        return None
    data = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", f"0:{pics[0]}",
                "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], binary=True).stdout
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img.thumbnail((max_side, max_side))
        return img
    except Exception:
        return None


def frame_at(path, seconds, max_side=MAX_SIDE):
    """A frame of the video at the given time, full width up to max_side, as a PIL image."""
    data = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(seconds, 0):.3f}", "-i", str(path),
                "-frames:v", "1", "-vf", f"scale='min({max_side},iw)':-2", "-f", "image2pipe", "-c:v", "png", "-"],
               binary=True).stdout
    if not data:
        return None
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def picture_from_file(path, max_side=MAX_SIDE):
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        return img


def _save_jpg(img, folder):
    target = Path(folder) / "cover.jpg"
    img.convert("RGB").save(target, "JPEG", quality=92)
    return target


def _replace(original, new_file, log, keep_date=False):
    """Put new_file where the original is; the original goes to the Recycle Bin. With keep_date the file keeps
    its modified date (File Explorer may then keep showing its old thumbnail until its cache is cleared)."""
    st = os.stat(original)
    backup = fileops.unique_path(original.parent, original.stem + " (original)" + original.suffix)
    os.replace(original, backup)  # step aside, so the name is free
    try:
        os.replace(new_file, original)
    except OSError:
        os.replace(backup, original)  # put everything back as it was
        raise
    if keep_date:
        os.utime(original, (st.st_atime, st.st_mtime))
    try:
        fileops.recycle(backup)
        log(f"  the original is in the Recycle Bin as {backup.name}")
    except fileops.RecycleError as exc:
        log(f"  {exc} The original is kept beside it as {backup.name}.")
    _tell_explorer(original)


def _tell_explorer(path):
    """Ask File Explorer to redraw this file, so the new thumbnail shows without a restart."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        SHCNE_UPDATEITEM, SHCNE_UPDATEDIR, SHCNF_PATHW = 0x00002000, 0x00001000, 0x0005
        ctypes.windll.shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, ctypes.c_wchar_p(str(path)), None)
        ctypes.windll.shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, ctypes.c_wchar_p(str(Path(path).parent)),
                                             None)
    except Exception:
        pass


def _check(new_file, original):
    """The new file must play for as long as the original and have the same sound and video."""
    a, b = probe_video(original), probe_video(new_file)
    if not b.get("duration"):
        raise RuntimeError("the new file couldn't be read back, so the original was left as it was")
    if a.get("duration") and abs(a["duration"] - b["duration"]) > 0.5:
        raise RuntimeError("the new file's length didn't match, so the original was left as it was")
    real = lambda s: sorted((k, n) for _i, k, pic, n in s if not pic and k in ("video", "audio"))
    if real(_streams(original)) != real(_streams(new_file)):
        raise RuntimeError("the new file's streams didn't match, so the original was left as it was")


def set_cover(path, picture, log=print, keep_date=False):
    """Make picture (a PIL image) the video's thumbnail. Raises with a plain reason when it can't."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise RuntimeError(why_not(path))
    work = Path(tempfile.mkdtemp(prefix="cover-", dir=path.parent))  # same drive, so the swap is instant
    try:
        cover = _save_jpg(picture, work)
        out = work / ("new" + ext)
        streams = _streams(path)
        covers = set(_cover_streams(path))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path)]
        if ext in MP4_LIKE:
            keep = [i for i, kind, pic, _n in streams if i not in covers and kind in ("video", "audio", "subtitle")]
            real_video = sum(1 for i, kind, _pic, _n in streams if kind == "video" and i in keep)
            cmd += ["-i", str(cover)]
            for i in keep:
                cmd += ["-map", f"0:{i}"]
            cmd += ["-map", "1:0", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy",
                    f"-disposition:v:{real_video}", "attached_pic", "-movflags", "+faststart"]
        else:
            # MKV: everything but the old cover (subtitles, fonts and chapters too), plus cover.jpg attached
            if _other_pictures(path):
                raise RuntimeError("this MKV has other pictures attached, which FFmpeg can't copy back, so it "
                                   "was left as it is")
            keep = [i for i, _kind, pic, _n in streams if i not in covers and not pic]
            fonts = sum(1 for i, kind, _p, _n in streams if kind == "attachment" and i in keep)
            for i in keep:
                cmd += ["-map", f"0:{i}"]
            cmd += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy", "-attach", str(cover),
                    f"-metadata:s:t:{fonts}", "mimetype=image/jpeg", f"-metadata:s:t:{fonts}", "filename=cover.jpg"]
        cmd.append(str(out))
        result = run(cmd)
        if result.returncode != 0 or not out.exists():
            lines = (result.stderr or "").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "FFmpeg couldn't write the new file")
        _check(out, path)
        _replace(path, out, log, keep_date)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # our own temporary folder


def remove_cover(path, log=print, keep_date=False):
    """Take the cover picture out, so Windows goes back to showing a frame."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise RuntimeError(why_not(path))
    if not has_cover(path):
        return False
    work = Path(tempfile.mkdtemp(prefix="cover-", dir=path.parent))
    try:
        out = work / ("new" + ext)
        if _other_pictures(path):
            raise RuntimeError("this MKV has other pictures attached, which FFmpeg can't copy back, so it was left "
                               "as it is")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-map", "0"]
        for i in _cover_streams(path):
            cmd += ["-map", f"-0:{i}"]
        cmd += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]
        if ext in MP4_LIKE:
            cmd += ["-movflags", "+faststart"]
        cmd.append(str(out))
        result = run(cmd)
        if result.returncode != 0 or not out.exists():
            lines = (result.stderr or "").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "FFmpeg couldn't write the new file")
        _check(out, path)
        _replace(path, out, log, keep_date)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def apply(jobs_, log=print, progress=None, state=None, keep_date=False):
    """jobs_: [(path, ("frame", seconds) | ("percent", 0-100) | ("file", picture path) | ("remove", None))].
    Returns (done, failed)."""
    progress = progress or noop
    state = state or noop
    total = len(jobs_)
    done, failed = 0, 0
    for n, (path, (how, value)) in enumerate(jobs_, 1):
        name = Path(path).name
        progress(n - 1, total, f"{'Removing the thumbnail from' if how == 'remove' else 'Setting the thumbnail of'} "
                               f"{name}")
        state(path, "Working", "")
        try:
            if how == "remove":
                changed = remove_cover(path, log, keep_date)
                log(f"[{n}/{total}] {name}: " + ("thumbnail removed" if changed else "had no thumbnail of its own"))
            else:
                if how == "file":
                    picture = picture_from_file(value)
                else:
                    seconds = value
                    if how == "percent":
                        seconds = (probe_video(path).get("duration") or 0) * value / 100
                    picture = frame_at(path, seconds)
                    if picture is None:
                        raise RuntimeError("that frame couldn't be read")
                set_cover(path, picture, log, keep_date)
                log(f"[{n}/{total}] {name}: new thumbnail set")
            done += 1
            state(path, "Done", "Thumbnail removed" if how == "remove" else "New thumbnail")
        except Exception as exc:
            if exc.__class__.__name__ == "JobStopped":
                raise
            failed += 1
            log(f"[{n}/{total}] {name}: {exc}")
            state(path, "Failed", str(exc))
    progress(total, total, "Done")
    return done, failed

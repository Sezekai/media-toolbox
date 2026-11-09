# Media Toolbox

Small, everyday tools for your own videos and pictures, in one portable Windows program.

## What it does

| Tool | What it's for |
|---|---|
| **Silent videos** | Finds videos with no sound (or, if you like, very quiet ones) in one or more folders, then moves the ones you tick to another folder. Every move can be undone. |
| **GIF maker** | Turns videos into GIFs. Each video can have its own timeframe, frame rate, width and file name; tick several to set them together. "Match each video" keeps every video's own frame rate and width. |
| **Duplicate videos** | Finds copies of a video, including smaller re-encodes and clips cut from a longer video, using [Video Duplicate Finder](https://github.com/0x90d/videoduplicatefinder)'s engine. Search a folder, or check new videos against a library one at a time. Uses an NVIDIA GPU when there is one. |
| **WebP to JPG** | Converts `.webp` pictures to `.jpg` beside each original, and can send the originals to the Recycle Bin. |
| **Zip subfolders** | Makes one `.zip` per folder inside a folder. |
| **Copy folder structure** | Recreates a folder's folders somewhere else, without the files. |

Plus: **Look** (themes, colours, fonts, corners and spacing), **Settings** (behaviour, the duplicate engine, storage, Diagnose and Repair, resets) and **Keys**.

### Safe by design
- Nothing is ever deleted for good: removals go to the Recycle Bin and are written to `deletions.csv`.
- Every move goes into the move log (press **L**, then **Moves**) with **Undo**. **Ctrl+Z** undoes the last one.
- Moves are shown for review first: untick a file to leave it, or change where it goes.
- Nothing is downloaded without asking first, and the question says what, how big, and where it goes.
- Long jobs show a progress bar, percentage, time elapsed and time left. Downloads also show MB and MB/s. Long jobs can be paused or stopped, and new jobs wait in a queue.

## Where things live

Keep the program in a folder of its own, for example `D:\Media Toolbox\App\MediaToolbox.exe`. If that folder is called `App`, the big folders go beside it in `D:\Media Toolbox`; otherwise they go beside the program.

| What | Where |
|---|---|
| Settings, results, move log, logs | `%LOCALAPPDATA%\Media Toolbox` (`logs` inside it; a crash leaves `crash-<date>.txt`) |
| Duplicate engine | `Models\vdf-cli` |
| FFmpeg for the engine | `Models\ffmpeg` (copied from the program) |
| Fingerprints of scanned videos | `Fingerprints` |
| Thumbnails, temporary files | `Cache\thumbs`, `Cache\temp` |

Any of these can be moved to another drive in **Settings › Storage**. If a drive isn't connected, the app says which and offers Retry or Choose a new place; it never makes the folder somewhere else. Version 1's files in `%APPDATA%\Media Toolbox` are moved into these places the first time version 2 starts.

If the app closes unexpectedly twice in a row, it starts in safe mode (no GPU decoding, no hover previews, the standard Windows title bar) and offers to turn them back on.

## Keys

Single letters work when you're not typing in a box.

| Key | Does |
|---|---|
| K / S | Keys / Settings |
| L | Open or close the log |
| M | Hide or show the side rail |
| H | Hide toolbars and side panels |
| F or F11 | Full screen |
| / or Ctrl+F | Go to the filter box |
| Esc | Close or leave, innermost first |
| Ctrl+Z | Undo the last move |
| Ctrl+A | Tick everything shown (again to untick) |
| Space | Tick the selected item |
| ← → PgUp PgDn Home End | Move between items |
| + − or Ctrl+wheel | Bigger or smaller pictures and cards |
| 0 / 1 | Gallery: fit, or actual size |
| Ctrl+Shift+I | Copy a debug report |

## Download

Every push to `main` builds the program, tests it and publishes a numbered release: see [Releases](../../releases). Download `MediaToolbox.exe` from the newest one.

## Build and test it yourself

```
pip install -r requirements.txt pytest
python -m pytest tests        # the tests
python main.py                # run from source (uses dev-root\ beside the code)
```

To build the .exe, put `ffmpeg.exe` and `ffprobe.exe` in this folder and run `build.bat`. It ends by running the built program's self-test (`MediaToolbox.exe --selftest <folder>`), which opens every screen off-screen, saves pictures of them, checks FFmpeg and exits with 0 when everything works.

Raise the number in `version.py` to publish a new release; a push with an unchanged number builds and tests but doesn't publish.

## Licences

Media Toolbox's own code is yours. FFmpeg (bundled) is from gyan.dev's builds (GPL). The duplicate engine, vdf-cli, is AGPL-3.0 and is downloaded separately when you ask; it isn't part of this program or this repository. Fonts in `fonts\` are under the SIL Open Font License or the Ubuntu Font Licence (each folder has its licence).

# Media Toolbox

Small, everyday tools for your own videos and pictures, in one portable Windows program.

## What it does

| Tool | What it's for |
|---|---|
| **Silent videos** | Finds videos with no sound (or, if you like, very quiet ones) in one or more folders, then moves the ones you tick to another folder. Every move can be undone. Shows each video's length (sort by it too) and has filters: rules like *Length shorter than 10 seconds* or *Size smaller than 5 MB*, matching all or any of them. **Tick all N** ticks everything you're looking at. Enter opens Gallery, T or the mouse's back button returns, and clicking the video plays or pauses it. |
| **GIF maker** | Turns videos into GIFs. Each video can have its own timeframe, frame rate, width and file name; tick several to set them together. "Match each video" keeps every video's own frame rate and width. |
| **Video thumbnails** | Chooses the picture File Explorer shows for a video: any frame from it, or any picture. Pick one per video, or for every ticked video at once (for example the frame 30% of the way in), then set them all. The video and sound are copied, not re-encoded, and each original goes to the Recycle Bin. MP4 and M4V show in File Explorer; MKV needs a thumbnail add-on such as Icaros. |
| **Make stills** | Takes two pictures from each video, one a second in and one from the middle, named `video - start.jpg` and `video - middle.jpg`, to search in Google Lens. The names match Lens Library's Import. Videos that already have both stills are skipped. |
| **Duplicate videos** | Finds copies of a video, including smaller re-encodes and clips cut from a longer video, using [Video Duplicate Finder](https://github.com/0x90d/videoduplicatefinder)'s engine. Search a folder, or check new videos against a library one at a time. Uses an NVIDIA GPU when there is one. |
| **WebP to JPG** | Converts `.webp` pictures to `.jpg` beside each original, and can send the originals to the Recycle Bin. |
| **Zip subfolders** | Makes one `.zip` per folder inside a folder. |
| **Copy folder structure** | Recreates a folder's folders somewhere else, without the files. |
| **Downloads** | Runs [gallery-dl](https://codeberg.org/mikf/gallery-dl) with a memory. Every download remembers what it fetched, so running it again downloads only what's new, even after you've moved or sorted the files. Two Twitter bookmark accounts (Main and Second, or both one after the other) share one history, so a tweet saved on either account downloads once. Any other page gallery-dl supports can be downloaded with its options laid out (folder, file names, login, kinds of file, dates, sizes, speed, extras), saved under a name, edited and saved again. Downloads run without saving go to Recent with their history; deleting one sends its history to the Recycle Bin. |

### How Downloads knows what's new
Each run first scans the page without downloading, then downloads exactly the new files, so the progress bar has a real total. History is gallery-dl's own download archive: Twitter files are remembered by tweet and picture number, so a retweet of something you have is skipped and moving files never makes them download again. For bookmarks (newest first) the scan stops at the files you kept from last time (on the first run, the files already in the folder), at the tweets that were at the top of the last run, or after five known tweets in a row; a tweet you bookmark again jumps to the top and never stops it early. "Stop after N in a row" (50) is the safety net. **Also skip files already in** lists the folders you sort downloads into: new files whose names are already there are remembered without downloading. Before each bookmarks run the app reads which Twitter account Firefox is signed in to and, for **Both**, waits for you to switch accounts in Firefox before doing the second one.

Plus: **Look** (themes, colours, fonts, corners and spacing), **Settings** (behaviour, the duplicate engine, storage, Diagnose and Repair, resets) and the **keyboard shortcuts popup** (K, on any screen).

### Drag and drop
Drag folders or files from File Explorer onto any tool instead of choosing them: folders and matching files are added to the list (videos for Silent videos, GIF maker and Video thumbnails; `.webp` pictures for WebP to JPG). On Duplicate videos, a folder becomes the folder to search (or the library), and videos are added to "Videos to check". On Zip subfolders and Copy folder structure, a folder becomes the folder to work on.

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
| gallery-dl (if downloaded by the app) | `Models\gallery-dl` (or your own `gallery-dl.exe`, chosen in Settings) |
| Downloads lists and histories | `%LOCALAPPDATA%\Media Toolbox\Downloads` (`downloads.json`, `history\*.sqlite3`) |
| Fingerprints of scanned videos | `Fingerprints` |
| Thumbnails, temporary files | `Cache\thumbs`, `Cache\temp` |

Any of these can be moved to another drive in **Settings › Storage**. If a drive isn't connected, the app says which and offers Retry or Choose a new place; it never makes the folder somewhere else. Version 1's files in `%APPDATA%\Media Toolbox` are moved into these places the first time version 2 starts.

If the app closes unexpectedly twice in a row, it starts in safe mode (no GPU decoding, no hover previews, the standard Windows title bar) and offers to turn them back on.

## Keys

Single letters work when you're not typing in a box.

| Key | Does |
|---|---|
| K | Open or close the keyboard shortcuts popup (also Keys in the rail; Esc or a click outside closes it) |
| S | Settings |
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

Every push to `main` builds the program, tests it and publishes a numbered release: see [Releases](../../releases). The first time, download `MediaToolbox-v<version>-windows.zip` from the newest one and unzip it where you want the app. After that, **Settings › Updates** checks once a day and updates from inside the app (with progress), so there's nothing to download by hand.

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

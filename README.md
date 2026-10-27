# Media Toolbox

A small Windows GUI for everyday file tasks.

## Tools
- **Silent videos:** lists videos with no audio track. Optionally also checks for silent audio (peak volume below a threshold, default -60 dB). Move the listed files to another folder.
- **Zip subfolders:** zips each subfolder of a parent folder into `FolderName.zip`.
- **WebP to JPG:** converts `.webp` files to `.jpg` in the same folder. Optionally sends the originals to the Recycle Bin.
- **Copy folder structure:** copies a folder's directories (without files) into another location.

## Setup (developers)
1. Install Python 3.10+ and FFmpeg (https://ffmpeg.org). Make sure `ffmpeg` and `ffprobe` work from a terminal.
2. Run `build.bat`. It installs the requirements, builds `dist\MediaToolbox.exe`, and pauses.

## Running from source
    pip install -r requirements.txt
    python main.py

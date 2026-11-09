@echo off
rem Builds dist\MediaToolbox.exe. Put ffmpeg.exe and ffprobe.exe in this folder first so they're bundled.
pip install -r requirements.txt
pyinstaller --noconsole --onefile --name MediaToolbox --add-data "fonts;fonts" --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." main.py
dist\MediaToolbox.exe --selftest selftest
type selftest\selftest.txt
pause

@echo off
rem Builds MediaToolbox.exe in the dist folder. Run from this folder.
pip install -r requirements.txt
pyinstaller --noconsole --onefile --name MediaToolbox --add-data "fonts;fonts" main.py
echo.
echo Done. The app is at dist\MediaToolbox.exe
echo Make sure ffmpeg and ffprobe are on your PATH (or copy them next to the exe).
pause

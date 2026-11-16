@echo off
rem Builds dist\MediaToolbox.exe. Put ffmpeg.exe and ffprobe.exe in this folder first so they're bundled.
pip install -r requirements.txt
python build_files.py
pyinstaller --noconsole --onefile --name MediaToolbox --add-data "fonts;fonts" --icon MediaToolbox.ico --version-file version_info.txt --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." main.py
dist\MediaToolbox.exe --selftest selftest
type selftest\selftest.txt
pause

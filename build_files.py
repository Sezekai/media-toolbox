"""Files the build puts into the .exe: its icon, and the version details File Explorer shows (Properties ›
Details). Run before PyInstaller: `python build_files.py`."""
import app_icon
from version import __version__

parts = [int(p) for p in __version__.split(".")] + [0] * 4
nums = ", ".join(str(n) for n in parts[:4])

app_icon.write_ico("MediaToolbox.ico")
with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080904b0', [
      StringStruct('CompanyName', 'Sezekai'),
      StringStruct('FileDescription', 'Media Toolbox'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'MediaToolbox'),
      StringStruct('LegalCopyright', 'Sezekai'),
      StringStruct('OriginalFilename', 'MediaToolbox.exe'),
      StringStruct('ProductName', 'Media Toolbox'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [2057, 1200])])
  ]
)
""")
print(f"Wrote MediaToolbox.ico and version_info.txt for {__version__}")

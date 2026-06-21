# Build NoticeDataPrinter.exe

This builds only the Python GUI + localhost bridge into an EXE. The Chrome extension is still installed separately with `Load unpacked`.

## Fast build on Windows

Open CMD in this folder:

```bat
build_exe.bat
```

Output:

```txt
dist\NoticeDataPrinter.exe
```

## Debug build

If the EXE opens and closes or something is wrong:

```bat
build_exe_debug.bat
```

Then run:

```bat
dist\NoticeDataPrinterDebug.exe
```

The debug version keeps a console window so you can see errors.

## Manual command

```bat
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name NoticeDataPrinter ^
  --add-data "templates;templates" ^
  --add-data "placeholder_maps;placeholder_maps" ^
  --add-data "examples;examples" ^
  --collect-data tldextract ^
  --collect-data PIL ^
  --hidden-import PIL._tkinter_finder ^
  gui_notice_data.py
```

## Common notes

- First launch may be slower because `--onefile` extracts files to a temp folder.
- Windows Defender may scan the EXE on first run.
- If Microsoft Store Python causes packaging issues, install Python from python.org and rerun the build.

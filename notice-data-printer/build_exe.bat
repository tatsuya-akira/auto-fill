@echo off
setlocal
cd /d "%~dp0"

echo Installing requirements and PyInstaller...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo.
echo Building NoticeDataPrinter.exe...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name NoticeDataPrinter ^
  --add-data "templates;templates" ^
  --add-data "placeholder_maps;placeholder_maps" ^
  --add-data "examples;examples" ^
  --collect-data tldextract ^
  --collect-data PIL ^
  --hidden-import PIL._tkinter_finder ^
  gui_notice_data.py

echo.
echo Done. EXE path:
echo %CD%\dist\NoticeDataPrinter.exe
pause

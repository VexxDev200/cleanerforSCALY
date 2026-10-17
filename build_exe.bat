@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller -q
pyinstaller --noconfirm --onefile --windowed --name ScalyCleaner ^
  --collect-all customtkinter ^
  --hidden-import=PIL._tkinter_finder ^
  main.py
echo.
echo Готово: dist\ScalyCleaner.exe
echo Перед выкладкой обнови releases\version.json и залей exe в GitHub Release.
pause

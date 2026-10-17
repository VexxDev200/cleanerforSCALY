@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tools\build_release.py
if errorlevel 1 exit /b 1
echo.
echo Готово. Раздай dist\ScalyCleaner-portable или ZIP.
pause

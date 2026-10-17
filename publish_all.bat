@echo off
REM Build release (same version). New version: .\release_new.bat
REM PowerShell: .\publish_all.bat
chcp 65001 >nul
cd /d "%~dp0"
python tools\generate_brand_assets.py
python tools\build_release.py
python tools\verify_auto_update.py
if errorlevel 1 exit /b 1
echo.
echo OK: dist\ScalyCleaner.exe
echo Next: powershell -ExecutionPolicy Bypass -File tools\setup_github_and_publish.ps1
pause

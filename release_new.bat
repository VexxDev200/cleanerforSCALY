@echo off
REM Bump patch version + build + verify
chcp 65001 >nul
cd /d "%~dp0"
python tools\bump_version.py
call publish_all.bat

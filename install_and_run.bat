@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\ScalyCleaner.exe" (
    start "" "dist\ScalyCleaner.exe"
    exit /b 0
)
where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (
    echo Python не найден. Скачай ScalyCleaner.exe из Releases на GitHub.
    pause
    exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
%PY% main.py
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\ScalyCleaner.exe" (
    powershell -NoProfile -Command "Start-Process -FilePath '%CD%\dist\ScalyCleaner.exe' -Verb RunAs"
    exit /b 0
)
where py >nul 2>&1 && set PY=py -3
if not defined PY set PY=python
%PY% -m pip install -q -r requirements.txt
powershell -NoProfile -Command "Start-Process -FilePath '%PY%' -ArgumentList '\"%CD%\main.py\"' -Verb RunAs -WorkingDirectory '%CD%'"

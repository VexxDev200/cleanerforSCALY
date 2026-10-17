@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList '\"%CD%\main.py\"' -Verb RunAs -WorkingDirectory '%CD%'"

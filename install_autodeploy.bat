@echo off
cd /d "%~dp0"
echo Installing SCALY auto-deploy (runs at Windows logon)...
set TASK=SCALYCleanerAutoDeploy
set PY=%LocalAppData%\Programs\Python\Python312\pythonw.exe
if not exist "%PY%" set PY=pythonw
schtasks /Create /F /TN "%TASK%" /TR "\"%PY%\" \"%~dp0tools\auto_deploy_watcher.py\"" /SC ONLOGON /RL LIMITED
echo Done. After save + ~45s changes push to GitHub automatically.
echo To remove: schtasks /Delete /F /TN %TASK%
pause

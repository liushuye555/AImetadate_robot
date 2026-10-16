@echo off
setlocal

REM Request a managed shutdown through the Qt manager.
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0stop-qq-onebot-whitelist-hidden.ps1"
exit /b %errorlevel%

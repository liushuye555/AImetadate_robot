@echo off
setlocal

REM Route all service starts through the project's control module.
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start-qq-onebot-whitelist-hidden.ps1"
exit /b %errorlevel%

@echo off
setlocal

REM Stop processes launched by start-qq-onebot-whitelist.bat.

echo Stopping QQ OneBot whitelist bot...
taskkill /FI "WINDOWTITLE eq QQ-OneBot-Whitelist-Bot*" /T /F >nul 2>nul

echo Stopping NapCat...
taskkill /FI "WINDOWTITLE eq NapCat-OneBot*" /T /F >nul 2>nul

echo Done. If any process remains, check Task Manager for node.exe or python.exe.
pause

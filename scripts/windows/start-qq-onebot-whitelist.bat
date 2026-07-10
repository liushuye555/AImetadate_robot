@echo off
setlocal

REM One-click launcher for NapCat + QQ OneBot whitelist bot.
REM This script does not depend on Hermes. It starts both long-running processes
REM in minimized command windows and writes logs under C:\Users\eryis\workspace\qq-onebot-whitelist\logs.

set "NAPCAT_DIR=D:\Hermes\Data\tools\napcat\NapCat.Shell.Windows.Node"
set "BOT_DIR=C:\Users\eryis\workspace\qq-onebot-whitelist"
set "LOG_DIR=%BOT_DIR%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "%NAPCAT_DIR%\napcat.bat" (
  echo [ERROR] NapCat launcher not found: "%NAPCAT_DIR%\napcat.bat"
  pause
  exit /b 1
)

if not exist "%BOT_DIR%\config.yaml" (
  echo [ERROR] Bot config not found: "%BOT_DIR%\config.yaml"
  pause
  exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv not found in PATH. Install uv or add it to PATH.
  pause
  exit /b 1
)

echo Starting NapCat...
start "NapCat-OneBot" /min cmd /c "cd /d "%NAPCAT_DIR%" && call napcat.bat >> "%LOG_DIR%\napcat.log" 2>&1"

echo Waiting for NapCat WebUI/OneBot to initialize...
timeout /t 8 /nobreak >nul

echo Starting QQ OneBot whitelist bot...
start "QQ-OneBot-Whitelist-Bot" /min cmd /c "cd /d "%BOT_DIR%" && if exist .env call .env && uv run python -m qq_onebot_whitelist.onebot --config config.yaml >> "%LOG_DIR%\bot.log" 2>&1"

echo.
echo Started.
echo NapCat WebUI: http://127.0.0.1:6099
echo OneBot WS:    ws://127.0.0.1:3001
echo Logs:
echo   %LOG_DIR%\napcat.log
echo   %LOG_DIR%\bot.log
echo.
echo If QQ is not logged in, open NapCat WebUI and scan the QR code.
pause

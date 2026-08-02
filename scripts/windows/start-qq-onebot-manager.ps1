$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'
$LegacyExe = Join-Path $BotDir 'manager\target\release\qq-onebot-manager.exe'
$FallbackTray = Join-Path $PSScriptRoot 'qq-onebot-tray.ps1'

if (Test-Path -LiteralPath $PanelExe) {
    Start-Process -FilePath $PanelExe -WorkingDirectory $BotDir | Out-Null
    exit 0
}

if (Test-Path -LiteralPath $LegacyExe) {
    Start-Process -FilePath $LegacyExe -WorkingDirectory $BotDir | Out-Null
    exit 0
}

# Keep the existing tray usable before the Rust release build is installed.
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
Start-Process -FilePath $PowerShell -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',"`"$FallbackTray`"") -WorkingDirectory $BotDir -WindowStyle Hidden | Out-Null

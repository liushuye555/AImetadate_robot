$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'

if (-not (Test-Path -LiteralPath $PanelExe)) {
    Write-Error "The Qt manager was not found: $PanelExe`nBuild it with qq-onebot-manager-qt\deploy.ps1, then run this launcher again."
    exit 1
}

# This is the interactive GUI itself; hiding it also hides Qt's native window.
# Console wrappers may stay hidden, but the requested manager must be visible.
Start-Process -FilePath $PanelExe -WorkingDirectory $BotDir -WindowStyle Normal | Out-Null

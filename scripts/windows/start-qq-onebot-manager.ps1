$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'

if (-not (Test-Path -LiteralPath $PanelExe)) {
    Write-Error "The Qt manager was not found: $PanelExe`nBuild it with qq-onebot-manager-qt\deploy.ps1, then run this launcher again."
    exit 1
}

# Qt shows its own window; avoid creating a visible launcher console.
Start-Process -FilePath $PanelExe -WorkingDirectory $BotDir -WindowStyle Hidden | Out-Null

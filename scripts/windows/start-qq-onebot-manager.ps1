param([ValidateSet('show', 'stop-services', 'restart-services')][string]$Action = 'show')

$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'

if (-not (Test-Path -LiteralPath $PanelExe)) {
    Write-Error "The Qt manager was not found: $PanelExe`nBuild it with qq-onebot-manager-qt\deploy.ps1, then run this launcher again."
    exit 1
}

# This is the interactive GUI itself; hiding it also hides Qt's native window.
# Console wrappers may stay hidden, but the requested manager must be visible.
$StopMarker = Join-Path $BotDir 'run\manager-user-stop'
New-Item -ItemType Directory -Path (Split-Path -Parent $StopMarker) -Force | Out-Null
if ($Action -eq 'stop-services') {
    [IO.File]::WriteAllText($StopMarker, [DateTimeOffset]::Now.ToString('o'))
} else {
    if (Test-Path -LiteralPath $StopMarker) { Remove-Item -LiteralPath $StopMarker }
    $State = Join-Path $BotDir 'run\manager-recovery-state.json'
    if (Test-Path -LiteralPath $State) { Remove-Item -LiteralPath $State }
}
if ($Action -eq 'show') {
    Start-Process -FilePath $PanelExe -WorkingDirectory $BotDir -WindowStyle Normal | Out-Null
} else {
    Start-Process -FilePath $PanelExe -ArgumentList "--$Action" -WorkingDirectory $BotDir -WindowStyle Hidden | Out-Null
}

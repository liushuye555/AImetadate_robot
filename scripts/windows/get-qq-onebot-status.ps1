$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $BotDir '.venv\Scripts\python.exe'
Push-Location $BotDir
try {
    & $Python -m qq_onebot_whitelist.control live-status
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

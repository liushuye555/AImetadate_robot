$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $BotDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Project Python was not found: $Python. Create the project .venv before stopping managed services."
    exit 1
}

Push-Location $BotDir
try {
    & $Python -m qq_onebot_whitelist.control stop
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

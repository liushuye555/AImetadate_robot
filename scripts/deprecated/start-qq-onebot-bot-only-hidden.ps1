$ErrorActionPreference = 'Stop'
$BotDir = 'C:\Users\eryis\workspace\qq-onebot-whitelist'
$LogDir = Join-Path $BotDir 'logs'
$PidDir = Join-Path $BotDir 'run'
New-Item -ItemType Directory -Force -Path $LogDir, $PidDir | Out-Null
$cmd = 'cd /d "' + $BotDir + '" && uv run python -m qq_onebot_whitelist.onebot --config config.yaml >> "' + (Join-Path $LogDir 'bot.log') + '" 2>&1'
$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/s','/c',$cmd) -WorkingDirectory $BotDir -WindowStyle Hidden -PassThru
Set-Content -Path (Join-Path $PidDir 'bot.pid') -Value $proc.Id -Encoding ASCII
Write-Host "bot pid $($proc.Id)"

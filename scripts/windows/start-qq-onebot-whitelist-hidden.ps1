$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$NapcatDir = Join-Path $BotDir 'runtime\NapCat.Shell.Windows.Node'
if ($env:NAPCAT_DIR) { $NapcatDir = $env:NAPCAT_DIR }
$LauncherConfig = Join-Path $PSScriptRoot 'launcher.config.ps1'
if (Test-Path $LauncherConfig) { . $LauncherConfig }
$LogDir = Join-Path $BotDir 'logs'
$PidDir = Join-Path $BotDir 'run'

New-Item -ItemType Directory -Force -Path $LogDir, $PidDir | Out-Null

$NapcatBat = Join-Path $NapcatDir 'napcat.bat'
$Config = Join-Path $BotDir 'config.yaml'
if (-not (Test-Path $NapcatBat)) { throw "NapCat launcher not found: $NapcatBat" }
if (-not (Test-Path $Config)) { throw "Bot config not found: $Config" }

function Test-PortOpen {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(600)
        if ($ok) { $client.EndConnect($async) }
        $client.Close()
        return [bool]$ok
    } catch {
        return $false
    }
}

function Test-OwnedProcessByPidFile {
    param([string]$PidPath, [string]$Needle)
    if (-not (Test-Path $PidPath)) { return $false }
    $text = Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    $procId = 0
    if (-not [int]::TryParse($text, [ref]$procId)) { return $false }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    return [bool]($process -and $process.CommandLine -and $process.CommandLine -like "*$Needle*")
}

function Test-CommandLineContains {
    param([string]$Needle)
    $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Needle*" }
    return [bool]($procs | Select-Object -First 1)
}

function Start-HiddenProcess {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$Command,
        [string]$LogPath,
        [string]$PidPath
    )
    $cmd = "cd /d `"$WorkingDirectory`" && $Command >> `"$LogPath`" 2>&1"
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/s','/c',$cmd) -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
    Set-Content -Path $PidPath -Value $proc.Id -Encoding ASCII
    Write-Host "$Name PID $($proc.Id)"
}

$napcatPid = Join-Path $PidDir 'napcat.pid'
$botPid = Join-Path $PidDir 'bot.pid'

$napcatRunning = (Test-PortOpen 6099) -or (Test-OwnedProcessByPidFile -PidPath $napcatPid -Needle $NapcatDir) -or (Test-CommandLineContains $NapcatDir)
if ($napcatRunning) {
    Write-Host 'NapCat already appears to be running; skipping NapCat start.'
} else {
    Start-HiddenProcess -Name 'NapCat' `
        -WorkingDirectory $NapcatDir `
        -Command 'call napcat.bat' `
        -LogPath (Join-Path $LogDir 'napcat.log') `
        -PidPath $napcatPid
}

# Wait for OneBot WebSocket port. NapCat opens it after QQ login and OB11 config is active.
$deadline = (Get-Date).AddMinutes(5)
$onebotReady = $false
while ((Get-Date) -lt $deadline) {
    if (Test-PortOpen 3001) { $onebotReady = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $onebotReady) {
    Write-Host 'OneBot WS port 3001 is not ready. Open NapCat WebUI, login QQ, and ensure OB11 WebSocket server is enabled.'
    Write-Host 'NapCat WebUI: http://127.0.0.1:6099'
    exit 2
}

$botProc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*qq_onebot_whitelist.onebot*' -and $_.CommandLine -like "*$BotDir*" -and $_.Name -in @('cmd.exe','uv.exe','python.exe') } | Select-Object -First 1
$botRunning = (Test-OwnedProcessByPidFile -PidPath $botPid -Needle $BotDir) -or [bool]$botProc
if ($botRunning) {
    Write-Host 'QQ OneBot whitelist bot already appears to be running; skipping bot start.'
} else {
    Start-HiddenProcess -Name 'QQ OneBot whitelist bot' `
        -WorkingDirectory $BotDir `
        -Command ('uv run python -m qq_onebot_whitelist.onebot --config "' + $Config + '"') `
        -LogPath (Join-Path $LogDir 'bot.log') `
        -PidPath $botPid
}

Write-Host 'Ready.'
Write-Host 'NapCat WebUI: http://127.0.0.1:6099'
Write-Host 'OneBot WS: ws://127.0.0.1:3001'
Write-Host "Logs: $LogDir"

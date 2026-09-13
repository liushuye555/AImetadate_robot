$ErrorActionPreference = 'Continue'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DefaultNapcatDir = Join-Path $BotDir 'runtime\NapCat.Shell.Windows.Node'
$NapcatDir = $DefaultNapcatDir
if ($env:NAPCAT_DIR) { $NapcatDir = $env:NAPCAT_DIR }
$LauncherConfig = Join-Path $PSScriptRoot 'launcher.config.ps1'
if (Test-Path $LauncherConfig) { . $LauncherConfig }
if (-not (Test-Path $NapcatDir)) { $NapcatDir = $DefaultNapcatDir }
$NapcatNeedle = $NapcatDir
$PidDir = Join-Path $BotDir 'run'

# Mark an intentional stop before killing anything. The Qt tray monitor reads
# this heartbeat and must not interpret the shutdown window as a crash.
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null
$ManualStopPath = Join-Path $PidDir 'manual-stop'
Set-Content -LiteralPath $ManualStopPath -Value 'stop' -Encoding ascii
$StatusPath = Join-Path $PidDir 'status.json'
$StatusTmpPath = Join-Path $PidDir 'status.json.stop.tmp'
try {
    $status = [ordered]@{
        napcat = $false
        onebot = $false
        bot = $false
        qqLoggedIn = $false
        qqNumber = ''
        qqNickname = ''
        collectionPaused = Test-Path (Join-Path $PidDir 'collection-paused')
        manualStop = $true
        updatedAt = (Get-Date).ToString('o')
    }
    [System.IO.File]::WriteAllText(
        $StatusTmpPath,
        ($status | ConvertTo-Json -Compress),
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::Move($StatusTmpPath, $StatusPath, $true)
} catch {
}

function Stop-TreeByPid {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($child in $children) { Stop-TreeByPid -ProcessId ([int]$child.ProcessId) }
    try {
        taskkill /PID $ProcessId /F > $null 2>&1
    } catch {}
}

function Test-OwnedProcess {
    param([int]$ProcessId, [string]$Needle)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    return [bool]($process -and $process.CommandLine -and $process.CommandLine -like "*$Needle*")
}

$pidFiles = @(
    @{ Name = 'bot.pid'; Needle = $BotDir },
    @{ Name = 'napcat.pid'; Needle = $NapcatNeedle }
)
foreach ($file in $pidFiles) {
    $path = Join-Path $PidDir $file.Name
    if (Test-Path $path) {
        $text = (Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1)
        $procId = 0
        if ([int]::TryParse($text, [ref]$procId) -and (Test-OwnedProcess -ProcessId $procId -Needle $file.Needle)) {
            Stop-TreeByPid -ProcessId $procId
        }
        Remove-Item $path -Force -ErrorAction SilentlyContinue
    }
}

# Fallback: stop remaining user-owned processes whose command line clearly belongs to NapCat or the bot.
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (($NapcatNeedle -and $_.CommandLine -like "*$NapcatNeedle*") -or ($_.CommandLine -like '*qq_onebot_whitelist.onebot*' -and $_.CommandLine -like "*$BotDir*"))
}
foreach ($p in $procs) {
    Stop-TreeByPid -ProcessId ([int]$p.ProcessId)
}

$remaining = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (($NapcatNeedle -and $_.CommandLine -like "*$NapcatNeedle*") -or ($_.CommandLine -like '*qq_onebot_whitelist.onebot*' -and $_.CommandLine -like "*$BotDir*"))
}
if ($remaining) {
    Write-Error 'Failed to stop all QQ OneBot whitelist processes.'
    exit 1
}

Write-Host 'Stopped QQ OneBot whitelist bot and NapCat if they were running.'
exit 0

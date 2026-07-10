$ErrorActionPreference = 'Continue'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$NapcatNeedle = $env:NAPCAT_DIR
$LauncherConfig = Join-Path $PSScriptRoot 'launcher.config.ps1'
if (Test-Path $LauncherConfig) { . $LauncherConfig }
if ($NapcatDir) { $NapcatNeedle = $NapcatDir }
$PidDir = Join-Path $BotDir 'run'

function Stop-TreeByPid {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($child in $children) { Stop-TreeByPid -ProcessId ([int]$child.ProcessId) }
    try {
        taskkill /PID $ProcessId /F > $null 2>&1
    } catch {}
}

foreach ($file in @('bot.pid','napcat.pid')) {
    $path = Join-Path $PidDir $file
    if (Test-Path $path) {
        $text = (Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1)
        $procId = 0
        if ([int]::TryParse($text, [ref]$procId)) { Stop-TreeByPid -ProcessId $procId }
        Remove-Item $path -Force -ErrorAction SilentlyContinue
    }
}

# Fallback: stop remaining user-owned processes whose command line clearly belongs to NapCat or the bot.
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (($NapcatNeedle -and $_.CommandLine -like "*$NapcatNeedle*") -or $_.CommandLine -like '*qq_onebot_whitelist.onebot*')
}
foreach ($p in $procs) {
    Stop-TreeByPid -ProcessId ([int]$p.ProcessId)
}

Write-Host 'Stopped QQ OneBot whitelist bot and NapCat if they were running.'

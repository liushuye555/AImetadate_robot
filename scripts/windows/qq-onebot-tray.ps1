$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ViewPath = Join-Path $BotDir 'data\view\index.html'
$LogDir = Join-Path $BotDir 'logs'
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\QQOneBotWhitelistTray', [ref]$createdNew)
if (-not $createdNew) { exit 0 }

function Invoke-BotScript {
    param([string]$Name)
    $path = Join-Path $PSScriptRoot $Name
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', "`"$path`""
    ) -WorkingDirectory $BotDir -WindowStyle Hidden | Out-Null
}

function Open-Path {
    param([string]$Path)
    if (Test-Path $Path) { Start-Process $Path | Out-Null }
}

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$startItem = $menu.Items.Add('Start / check status')
$viewItem = $menu.Items.Add('Open local pages')
$logsItem = $menu.Items.Add('Open logs')
$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator)) | Out-Null
$stopItem = $menu.Items.Add('Stop bot and NapCat')
$exitItem = $menu.Items.Add('Exit tray (keep services running)')
$stopExitItem = $menu.Items.Add('Stop all and exit')

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = 'QQ OneBot whitelist bot'
$tray.ContextMenuStrip = $menu
$tray.Visible = $true

$startItem.add_Click({
    Invoke-BotScript 'start-qq-onebot-whitelist-hidden.ps1'
    $tray.ShowBalloonTip(2500, 'QQ OneBot', 'Starting or checking services in the background.', [System.Windows.Forms.ToolTipIcon]::Info)
})
$viewItem.add_Click({ Open-Path $ViewPath })
$logsItem.add_Click({ Open-Path $LogDir })
$stopItem.add_Click({
    Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1'
    $tray.ShowBalloonTip(2500, 'QQ OneBot', 'Stop command sent.', [System.Windows.Forms.ToolTipIcon]::Info)
})
$exitItem.add_Click({
    $tray.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$stopExitItem.add_Click({
    Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1'
    $tray.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$tray.add_DoubleClick({ Open-Path $ViewPath })

Invoke-BotScript 'start-qq-onebot-whitelist-hidden.ps1'
$tray.ShowBalloonTip(2500, 'QQ OneBot', 'Tray ready. Right-click to open pages or stop services.', [System.Windows.Forms.ToolTipIcon]::Info)
try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $tray.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}

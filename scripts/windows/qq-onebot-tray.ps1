$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ViewPath = Join-Path $BotDir 'data\view\index.html'
$LogDir = Join-Path $BotDir 'logs'
$RunDir = Join-Path $BotDir 'run'
$ManualStopPath = Join-Path $RunDir 'tray.manual-stop'
$StartSignalPath = Join-Path $RunDir 'tray.start-check'
$StatusScript = Join-Path $PSScriptRoot 'get-qq-onebot-status.ps1'
$LocaleFile = Join-Path $PSScriptRoot 'tray.i18n.json'
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$TrayLanguage = if ([Globalization.CultureInfo]::CurrentUICulture.Name -like 'zh-*') { 'zh-CN' } else { 'en-US' }
$TrayResource = $null
if (Test-Path -LiteralPath $LocaleFile) {
    try {
        $jsonText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($LocaleFile))
        $allResources = $jsonText | ConvertFrom-Json
        $TrayResource = $allResources.PSObject.Properties[$TrayLanguage].Value
    } catch { $TrayResource = $null }
}
function T {
    param([string]$Key, [string]$English)
    if ($script:TrayResource -and $script:TrayResource.PSObject.Properties[$Key]) { return [string]$script:TrayResource.PSObject.Properties[$Key].Value }
    return $English
}

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\QQOneBotWhitelistTray', [ref]$createdNew)
if (-not $createdNew) {
    Set-Content -Path $StartSignalPath -Value (Get-Date).ToString('o') -Encoding ASCII
    exit 0
}

function Invoke-BotScript {
    param([string]$Name, [switch]$Wait, [switch]$PassThru)
    $path = Join-Path $PSScriptRoot $Name
    $arguments = @('-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', "`"$path`"")
    if ($Wait) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $BotDir -WindowStyle Hidden -Wait | Out-Null
    } else {
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $BotDir -WindowStyle Hidden -PassThru
        if ($PassThru) { return $process }
    }
}

function Open-Path {
    param([string]$Path)
    if (Test-Path $Path) { Start-Process $Path | Out-Null }
}

function Get-ServiceStatus {
    try {
        $json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StatusScript
        return ($json | Select-Object -Last 1 | ConvertFrom-Json)
    } catch {
        return [pscustomobject]@{ napcat=$false; onebot=$false; bot=$false; qqLoggedIn=$false; qqNumber=''; qqNickname='' }
    }
}

function Get-AutoRestartEnabled {
    try {
        $json = & python -m qq_onebot_whitelist.config_bridge get --config (Join-Path $BotDir 'config.yaml')
        $config = ($json | Select-Object -Last 1 | ConvertFrom-Json)
        if ($null -ne $config.features -and $null -ne $config.features.auto_restart) {
            return [bool]$config.features.auto_restart
        }
    } catch { }
    return $true
}

function Start-Services {
    Remove-Item $ManualStopPath -Force -ErrorAction SilentlyContinue
    if (-not $script:StartProcess -or $script:StartProcess.HasExited) {
        $script:StartProcess = Invoke-BotScript 'start-qq-onebot-whitelist-hidden.ps1' -PassThru
    }
    $script:NextRestartAt = (Get-Date).AddSeconds(30)
}

function Stop-PendingLauncher {
    if ($script:StartProcess -and -not $script:StartProcess.HasExited) {
        Stop-Process -Id $script:StartProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $script:StartProcess = $null
}

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$napcatStatus = $menu.Items.Add((T 'napcat_check' 'NapCat: checking'))
$qqStatus = $menu.Items.Add((T 'qq_check' 'QQ: checking'))
$onebotStatus = $menu.Items.Add((T 'onebot_check' 'OneBot: checking'))
$botStatus = $menu.Items.Add((T 'bot_check' 'Bot: checking'))
foreach ($item in @($napcatStatus,$qqStatus,$onebotStatus,$botStatus)) { $item.Enabled = $false }
$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator)) | Out-Null
$startItem = $menu.Items.Add((T 'start' 'Start / check status'))
$restartItem = $menu.Items.Add((T 'restart' 'Restart bot and NapCat'))
$webuiItem = $menu.Items.Add((T 'webui' 'Open NapCat WebUI'))
$viewItem = $menu.Items.Add((T 'pages' 'Open local pages'))
$logsItem = $menu.Items.Add((T 'logs' 'Open logs'))
$settingsItem = $menu.Items.Add((T 'windows' 'Set analysis windows'))
$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator)) | Out-Null
$stopItem = $menu.Items.Add((T 'stop' 'Stop bot and NapCat'))
$stopExitItem = $menu.Items.Add((T 'stop_exit' 'Stop all and exit'))
$exitItem = $menu.Items.Add((T 'exit' 'Exit tray (keep services running)'))

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = (T 'bot_check' 'Bot: checking')
$tray.ContextMenuStrip = $menu
$tray.Visible = $true
$script:NextRestartAt = Get-Date
$script:StartProcess = $null

function Refresh-Status {
    $status = Get-ServiceStatus
    $napcatStatus.Text = (T 'napcat_prefix' 'NapCat: ') + $(if ($status.napcat) { T 'running' 'running' } else { T 'stopped' 'stopped' })
    $onebotStatus.Text = (T 'onebot_prefix' 'OneBot: ') + $(if ($status.onebot) { T 'connected' 'connected' } else { T 'disconnected' 'disconnected' })
    $botStatus.Text = (T 'bot_prefix' 'Bot: ') + $(if ($status.bot) { T 'running' 'running' } else { T 'stopped' 'stopped' })
    if ($status.qqLoggedIn) {
        $qqStatus.Text = "$(T 'qq_logged' 'QQ: ')$($status.qqNickname) ($($status.qqNumber))"
    } else {
        $qqStatus.Text = (T 'not_logged' 'QQ: not logged in')
    }
    $healthy = $status.napcat -and $status.onebot -and $status.bot -and $status.qqLoggedIn
    $tray.Text = if ($healthy) { T 'healthy' 'QQ OneBot: running' } else { T 'problem' 'QQ OneBot: service problem' }
    if ((Test-Path $StartSignalPath)) {
        Remove-Item $StartSignalPath -Force -ErrorAction SilentlyContinue
        Start-Services
    } elseif ((Get-AutoRestartEnabled) -and -not (Test-Path $ManualStopPath) -and -not $healthy -and (Get-Date) -ge $script:NextRestartAt -and (-not $script:StartProcess -or $script:StartProcess.HasExited)) {
        Start-Services
    }
}

$startItem.add_Click({ Start-Services; Refresh-Status })
$restartItem.add_Click({
    Set-Content -Path $ManualStopPath -Value 'restart' -Encoding ASCII
    Stop-PendingLauncher
    Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1' -Wait
    Start-Services
})
$webuiItem.add_Click({ Start-Process 'http://127.0.0.1:6099/' | Out-Null })
$viewItem.add_Click({ Open-Path $ViewPath })
$logsItem.add_Click({ Open-Path $LogDir })
$settingsItem.add_Click({ Invoke-BotScript 'set-analysis-windows.ps1' })
$stopItem.add_Click({
    Set-Content -Path $ManualStopPath -Value 'stop' -Encoding ASCII
    Stop-PendingLauncher
    Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1' -Wait
    Refresh-Status
})
$exitItem.add_Click({ $tray.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$stopExitItem.add_Click({
    Set-Content -Path $ManualStopPath -Value 'stop' -Encoding ASCII
    Stop-PendingLauncher
    Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1' -Wait
    $tray.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$tray.add_DoubleClick({ Open-Path $ViewPath })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 10000
$timer.add_Tick({ Refresh-Status })
$timer.Start()
Start-Services
Refresh-Status
$tray.ShowBalloonTip(2500, (T 'title' 'QQ OneBot'), (T 'started' 'Tray started. Status is shown in the right-click menu.'), [System.Windows.Forms.ToolTipIcon]::Info)
try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Dispose()
    $tray.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}

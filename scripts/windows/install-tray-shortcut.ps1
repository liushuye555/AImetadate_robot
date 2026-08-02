$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ManagerLauncher = Join-Path $PSScriptRoot 'start-qq-onebot-manager.ps1'
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'
$LegacyExe = Join-Path $BotDir 'manager\target\release\qq-onebot-manager.exe'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Shell = New-Object -ComObject WScript.Shell
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'QQ OneBot Bot.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'QQ OneBot Bot.lnk')
)

foreach ($Target in $Targets) {
    $Shortcut = $Shell.CreateShortcut($Target)
    if (Test-Path -LiteralPath $PanelExe) {
        $Shortcut.TargetPath = $PanelExe
        $Shortcut.Arguments = ''
        $Shortcut.IconLocation = "$PanelExe,0"
    } elseif (Test-Path -LiteralPath $LegacyExe) {
        $Shortcut.TargetPath = $LegacyExe
        $Shortcut.Arguments = ''
        $Shortcut.IconLocation = "$LegacyExe,0"
    } else {
        $Shortcut.TargetPath = $PowerShell
        $Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ManagerLauncher`""
        $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    }
    $Shortcut.WorkingDirectory = $BotDir
    $Shortcut.Description = 'Start QQ OneBot native manager'
    $Shortcut.Save()
    Write-Host "Created: $Target"
}

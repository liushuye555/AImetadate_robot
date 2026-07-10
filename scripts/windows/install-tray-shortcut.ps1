$ErrorActionPreference = 'Stop'

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$TrayScript = Join-Path $PSScriptRoot 'qq-onebot-tray.ps1'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Shell = New-Object -ComObject WScript.Shell
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'QQ OneBot Bot.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'QQ OneBot Bot.lnk')
)

foreach ($Target in $Targets) {
    $Shortcut = $Shell.CreateShortcut($Target)
    $Shortcut.TargetPath = $PowerShell
    $Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$TrayScript`""
    $Shortcut.WorkingDirectory = $BotDir
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    $Shortcut.Description = 'Start QQ OneBot whitelist bot tray'
    $Shortcut.Save()
    Write-Host "Created: $Target"
}

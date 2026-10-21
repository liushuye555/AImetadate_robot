param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'manager-recovery-common.ps1')
$TaskName = Get-QQOneBotRecoveryTaskName -BotDir $BotDir
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'
$Policy = Join-Path $BotDir 'run\manager-recovery-policy.json'

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq 'Running') {
        throw 'Stop the manager normally before removing its recovery task.'
    }
    if ($task) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    if (Test-Path -LiteralPath $Policy) { Remove-Item -LiteralPath $Policy }
    Write-Host 'Manager recovery removed.'
    exit 0
}
if (-not (Test-Path -LiteralPath $PanelExe)) { throw 'Build the Qt manager first.' }
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') {
    throw 'Stop the manager normally before updating its recovery task.'
}
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = New-ScheduledTaskPrincipal -UserId $userSid -LogonType Interactive -RunLevel Limited
$Python = Join-Path $BotDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Project Python was not found.' }
# Invoke the GUI executable's headless mode. A pythonw filename does not prove
# GUI subsystem: uv venv redirectors may still create a console window.
$action = New-ScheduledTaskAction -Execute $PanelExe -Argument '--check-recovery' -WorkingDirectory $BotDir
$trigger = New-ScheduledTaskTrigger -Once -At ([DateTime]::Now.AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Each tick exits immediately if the exact manager is alive or the user stopped it.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'QQ OneBot: check once per minute; respect explicit stop; at most 3 recoveries per 10 minutes.' `
    -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $Policy) -Force | Out-Null
[IO.File]::WriteAllText($Policy, '{"enabled":true}', [Text.UTF8Encoding]::new($false))
& (Join-Path $BotDir '.venv\Scripts\python.exe') -m qq_onebot_whitelist.manager_recovery --arm
if (($LASTEXITCODE -ne 0) -or (Test-Path -LiteralPath (Join-Path $BotDir 'run\manager-user-stop'))) {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Warning 'Recovery is installed but paused until the next explicit manager start.'
}
Write-Host 'Manager recovery configured: check each minute, at most 3 recoveries per 10 minutes; user stop stays stopped.'

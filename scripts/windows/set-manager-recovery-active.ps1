param([Parameter(Mandatory=$true)][ValidateSet('pause', 'resume')][string]$Action)

$ErrorActionPreference = 'Stop'
$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'manager-recovery-common.ps1')
$taskName = Get-QQOneBotRecoveryTaskName -BotDir $BotDir
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) { exit 0 } # Explicit start must never reinstall a removed task.

if ($Action -eq 'pause') {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
} else {
    $policyFile = Join-Path $BotDir 'run\manager-recovery-policy.json'
    if (-not (Test-Path -LiteralPath $policyFile)) { exit 0 }
    $policy = [IO.File]::ReadAllText($policyFile) | ConvertFrom-Json
    if ($policy.enabled -ne $true) { exit 0 }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
}
exit 0

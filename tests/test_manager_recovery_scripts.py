import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows task-control script')
@pytest.mark.parametrize('action,present,enabled,expected', [
    ('pause', True, True, 'pause'),
    ('pause', False, True, ''),
    ('resume', True, True, 'resume'),
    ('resume', True, False, ''),
    ('resume', False, True, ''),
])
def test_recovery_task_pause_resume_without_creating_tasks(tmp_path, action, present, enabled, expected):
    # Task cmdlets are mocked in an isolated PowerShell process. No live task
    # registration or user startup settings are touched by these tests.
    scripts = tmp_path / 'scripts/windows'
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / 'scripts/windows'
    for name in ('set-manager-recovery-active.ps1', 'manager-recovery-common.ps1'):
        shutil.copy2(source / name, scripts / name)
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'manager-recovery-policy.json').write_text(
        '{"enabled":' + str(enabled).lower() + '}', encoding='utf-8')
    calls = tmp_path / 'calls.txt'
    wrapper = tmp_path / 'wrapper.ps1'
    wrapper.write_text(r'''
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($env:TEST_TASK_EXISTS -eq '1') { [pscustomobject]@{TaskName=$TaskName} }
}
function Disable-ScheduledTask {
    param($TaskName)
    [IO.File]::AppendAllText($env:TEST_CALLS_FILE, 'pause')
}
function Enable-ScheduledTask {
    param($TaskName)
    [IO.File]::AppendAllText($env:TEST_CALLS_FILE, 'resume')
}
function Register-ScheduledTask { throw 'Must never recreate a removed task' }
& (Join-Path $PSScriptRoot 'scripts/windows/set-manager-recovery-active.ps1') -Action $args[0]
exit $LASTEXITCODE
''', encoding='utf-8')
    environment = os.environ | {'TEST_TASK_EXISTS': '1' if present else '0',
                               'TEST_CALLS_FILE': str(calls)}
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(wrapper), action], env=environment,
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (calls.read_text() if calls.exists() else '') == expected

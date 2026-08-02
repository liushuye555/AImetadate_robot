from pathlib import Path


WINDOWS_DIR = Path(__file__).parents[1] / "scripts" / "windows"


def read_script(name: str) -> str:
    return (WINDOWS_DIR / name).read_text(encoding="ascii")


def test_active_start_scripts_do_not_call_dot_env():
    for path in WINDOWS_DIR.glob("start-*"):
        assert "call .env" not in path.read_text(encoding="ascii").lower(), path.name


def test_hidden_scripts_default_to_local_napcat_with_optional_overrides():
    for name in (
        "start-qq-onebot-whitelist-hidden.ps1",
        "stop-qq-onebot-whitelist-hidden.ps1",
    ):
        script = read_script(name)
        assert "Join-Path $BotDir 'runtime\\NapCat.Shell.Windows.Node'" in script
        assert "$env:NAPCAT_DIR" in script
        assert "launcher.config.ps1" in script
        assert "$DefaultNapcatDir" in script
        assert "if (-not (Test-Path $NapcatDir))" in script


def test_tray_has_schedule_settings_and_safe_exit_order():
    script = read_script("qq-onebot-tray.ps1")
    assert "set-analysis-windows.ps1" in script
    assert script.index("Stop all and exit") < script.index(
        "Exit tray (keep services running)"
    )


def test_schedule_settings_use_settings_cli_contract():
    script = read_script("set-analysis-windows.ps1")
    command = "qq_onebot_whitelist.settings"
    assert command in script
    assert "--get" in script
    assert "--set" in script
    assert "--all-day" in script
    assert "'--json'" in script


def test_stop_all_exit_waits_for_stop_script():
    script = read_script("qq-onebot-tray.ps1")
    handler = script[script.index("$stopExitItem.add_Click"):]
    assert "Invoke-BotScript 'stop-qq-onebot-whitelist-hidden.ps1' -Wait" in handler


def test_stop_script_returns_success_after_best_effort_cleanup():
    script = read_script("stop-qq-onebot-whitelist-hidden.ps1")
    assert 'Test-OwnedProcess' in script
    assert 'if ($remaining)' in script
    assert 'exit 1' in script
    assert script.rstrip().endswith('exit 0')


def test_start_script_only_reuses_owned_processes():
    script = read_script("start-qq-onebot-whitelist-hidden.ps1")
    assert "Test-OwnedProcessByPidFile" in script
    assert "Test-OwnedProcessByPidFile -PidPath $botPid -Needle $BotDir" in script
    assert '$_.CommandLine -like "*$BotDir*"' in script


def test_tray_shortcut_uses_absolute_windows_powershell():
    script = read_script("install-tray-shortcut.ps1")
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in script
    assert "$Shortcut.TargetPath = $PowerShell" in script


def test_status_probe_reports_services_and_qq_login():
    script = read_script("get-qq-onebot-status.ps1")
    for field in ('napcat', 'onebot', 'bot', 'qqLoggedIn', 'qqNumber', 'qqNickname'):
        assert field in script
    assert 'ClientWebSocket' in script
    assert 'get_login_info' in script
    assert 'ConvertTo-Json' in script


def test_status_probe_forces_utf8_stdout_for_chinese_nicknames():
    script = read_script("get-qq-onebot-status.ps1")
    assert "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)" in script


def test_tray_shows_status_webui_and_supervises_services():
    script = read_script("qq-onebot-tray.ps1")
    assert 'Open NapCat WebUI' in script
    assert 'Restart bot and NapCat' in script
    assert 'get-qq-onebot-status.ps1' in script
    assert 'System.Windows.Forms.Timer' in script
    assert '$ManualStopPath' in script
    assert '$StartSignalPath' in script
    assert 'Get-AutoRestartEnabled' in script
    assert '(Get-AutoRestartEnabled) -and' in script
    assert 'AddSeconds(30)' in script
    assert 'NapCat:' in script
    assert 'QQ:' in script
    assert 'OneBot:' in script
    assert 'Bot:' in script


def test_second_tray_launch_signals_existing_instance():
    script = read_script("qq-onebot-tray.ps1")
    mutex_exit = script.index('if (-not $createdNew)')
    assert '$StartSignalPath' in script[:mutex_exit]
    assert 'Set-Content' in script[mutex_exit:mutex_exit + 300]


def test_manual_stop_cancels_pending_launcher():
    script = read_script("qq-onebot-tray.ps1")
    assert 'function Stop-PendingLauncher' in script
    stop_handler = script[script.index('$stopItem.add_Click'):]
    assert 'Stop-PendingLauncher' in stop_handler[:500]

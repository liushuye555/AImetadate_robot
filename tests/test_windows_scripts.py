from pathlib import Path


WINDOWS_DIR = Path(__file__).parents[1] / "scripts" / "windows"


def read_script(name: str) -> str:
    return (WINDOWS_DIR / name).read_text(encoding="utf-8-sig")


def test_active_start_scripts_do_not_call_dot_env():
    for path in WINDOWS_DIR.glob("start-*"):
        assert "call .env" not in path.read_text(encoding="utf-8-sig").lower(), path.name


def test_start_entry_points_delegate_to_python_control():
    hidden = read_script("start-qq-onebot-whitelist-hidden.ps1")
    assert "$Python -m qq_onebot_whitelist.control start" in hidden
    assert ".venv\\Scripts\\python.exe" in hidden
    assert "qq_onebot_whitelist.onebot" not in hidden
    assert "napcat.bat" not in hidden.lower()
    assert "Start-Process" not in hidden
    assert "Timer" not in hidden

    batch = read_script("start-qq-onebot-whitelist.bat")
    assert "start-qq-onebot-whitelist-hidden.ps1" in batch
    assert "qq_onebot_whitelist.onebot" not in batch
    assert "napcat.bat" not in batch.lower()


def test_stop_entry_points_delegate_to_python_control_without_killing_processes():
    hidden = read_script("stop-qq-onebot-whitelist-hidden.ps1")
    assert "$Python -m qq_onebot_whitelist.control stop" in hidden
    assert ".venv\\Scripts\\python.exe" in hidden
    for forbidden in ("taskkill", "Stop-Process", "napcat.bat", "qq_onebot_whitelist.onebot"):
        assert forbidden.lower() not in hidden.lower()

    batch = read_script("stop-qq-onebot-whitelist.bat")
    assert "stop-qq-onebot-whitelist-hidden.ps1" in batch
    assert "taskkill" not in batch.lower()


def test_manager_launcher_uses_qt_only_and_has_no_fallback():
    script = read_script("start-qq-onebot-manager.ps1")
    assert "qq-onebot-manager-qt\\build\\qq-onebot-manager-qt.exe" in script
    assert "Test-Path -LiteralPath $PanelExe" in script
    assert "Start-Process -FilePath $PanelExe" in script
    assert "Write-Error" in script and "exit 1" in script
    assert "LegacyExe" not in script
    assert "manager\\target" not in script
    assert "qq-onebot-tray.ps1" not in script


def test_legacy_tray_entry_redirects_before_watchdog_body():
    script = read_script("qq-onebot-tray.ps1")
    prefix = script.split("$ErrorActionPreference", maxsplit=1)[0]
    assert "start-qq-onebot-manager.ps1" in prefix
    assert "exit $LASTEXITCODE" in prefix
    assert prefix.index("start-qq-onebot-manager.ps1") < prefix.index("exit $LASTEXITCODE")
    assert "System.Windows.Forms" not in prefix
    assert "Start-Services" not in prefix
    assert "qq_onebot_whitelist.onebot" not in prefix


def test_schedule_settings_use_settings_cli_contract():
    script = read_script("set-analysis-windows.ps1")
    command = "qq_onebot_whitelist.settings"
    assert command in script
    assert "--get" in script
    assert "--set" in script
    assert "--all-day" in script
    assert "'--json'" in script


def test_tray_shortcut_uses_absolute_windows_powershell_fallback():
    script = read_script("install-tray-shortcut.ps1")
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in script
    assert "$Shortcut.TargetPath = $PowerShell" in script
    assert "$Shortcut.TargetPath = $PanelExe" in script


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

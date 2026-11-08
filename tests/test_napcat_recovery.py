"""A surviving bot must recover its missing independent NapCat process."""
import json
import os
from subprocess import Popen as NativePopen
from types import SimpleNamespace

import pytest

from qq_onebot_whitelist import control


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / 'project with spaces'
    launcher = root / 'runtime/NapCat.Shell.Windows.Node/napcat.bat'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('@echo off', encoding='ascii')
    monkeypatch.setattr(control, 'REPO_ROOT', root)
    monkeypatch.setattr(control, 'RUN_DIR', root / 'run')
    monkeypatch.setattr(control, 'require_manager', lambda _: {'session': 'current'})
    monkeypatch.setattr(control, 'port_open', lambda _: False)
    monkeypatch.setattr(control, 'process_identity', lambda _: '123456')
    monkeypatch.setattr(control, 'is_process_alive', lambda *_: False)
    calls = []
    monkeypatch.setattr(control.subprocess, 'Popen', lambda args, **kwargs:
                        calls.append((args, kwargs)) or SimpleNamespace(pid=901))
    return root, calls


def test_start_repairs_napcat_even_when_owned_bot_already_exists(runtime, monkeypatch):
    root, calls = runtime
    monkeypatch.setattr(control, 'read_owned_bot', lambda *_: 2468)
    assert control.start_services() == 2468
    assert len(calls) == 1
    assert isinstance(calls[0][0], str) and 'napcat.bat' in calls[0][0]
    assert calls[0][1]['creationflags'] & 0x01000000


def test_recovery_waits_for_starting_process_and_rate_limits_crash_loop(runtime, monkeypatch):
    root, calls = runtime
    assert control.ensure_napcat_running() is True
    monkeypatch.setattr(control, 'is_process_alive', lambda *_: True)
    assert control.ensure_napcat_running() is False
    monkeypatch.setattr(control, 'is_process_alive', lambda *_: False)
    assert control.ensure_napcat_running() is False
    assert len(calls) == 1
    state_path = root / 'run/napcat-recovery.json'
    state = json.loads(state_path.read_text())
    state['lastAttempt'] -= 61
    state_path.write_text(json.dumps(state))
    assert control.ensure_napcat_running() is True
    assert len(calls) == 2


@pytest.mark.parametrize('marker', ['manual-stop', 'manager-user-stop'])
def test_recovery_respects_explicit_stop(runtime, marker):
    root, calls = runtime
    (root / 'run').mkdir()
    (root / 'run' / marker).touch()
    assert control.ensure_napcat_running() is False
    assert not calls


def test_recovery_leaves_running_or_login_pending_napcat_alone(runtime, monkeypatch):
    _, calls = runtime
    monkeypatch.setattr(control, 'port_open', lambda port: port == control.NAPCAT_PORT)
    assert control.ensure_napcat_running() is False
    assert not calls


def test_recovery_refuses_without_live_manager(runtime, monkeypatch):
    _, calls = runtime
    monkeypatch.setattr(control, 'require_manager', lambda _:
                        (_ for _ in ()).throw(RuntimeError('manager gone')))
    with pytest.raises(RuntimeError, match='manager gone'):
        control.ensure_napcat_running()
    assert not calls


def test_parallel_launch_guard_prevents_second_spawn(runtime):
    _, calls = runtime
    with control._napcat_launch_guard() as acquired:
        assert acquired
        assert control.ensure_napcat_running() is False
    assert not calls
    assert control.ensure_napcat_running() is True


def test_failed_spawn_is_also_rate_limited(runtime, monkeypatch):
    _, calls = runtime
    def fail(*_args, **_kwargs):
        raise OSError('launch failed')
    monkeypatch.setattr(control.subprocess, 'Popen', fail)
    with pytest.raises(OSError, match='launch failed'):
        control.ensure_napcat_running()
    assert control.ensure_napcat_running() is False
    assert not calls


@pytest.mark.skipif(os.name != 'nt', reason='Windows cmd quoting integration')
def test_actual_windows_batch_launch_with_spaces_in_path(runtime, monkeypatch):
    root, _ = runtime
    launcher = root / 'runtime/NapCat.Shell.Windows.Node/napcat.bat'
    launcher.write_text('@echo off\n> "%~dp0started.txt" echo launched\nexit /b 0\n', encoding='ascii')
    processes = []
    def launch(command, **kwargs):
        process = NativePopen(command, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(control.subprocess, 'Popen', launch)
    try:
        assert control.ensure_napcat_running() is True
        assert processes[0].wait(timeout=10) == 0
        assert launcher.with_name('started.txt').read_text().strip() == 'launched'
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_invalid_bot_install_does_not_launch_napcat(runtime, monkeypatch):
    _, calls = runtime
    monkeypatch.setattr(control, 'read_owned_bot', lambda *_: None)
    with pytest.raises(RuntimeError, match='Python'):
        control.start_services()
    assert not calls

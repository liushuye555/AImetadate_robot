import json
from pathlib import Path

import pytest

from qq_onebot_whitelist import manager_recovery as recovery

IDENTITY = {'authenticationId': '12345', 'bootEstimateMs': 1000}


@pytest.fixture
def armed(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'manager-recovery-policy.json').write_text('{"enabled":true}', encoding='utf-8')
    (run / 'manager-recovery-armed.json').write_text(json.dumps(IDENTITY), encoding='utf-8')
    (run / 'manager-session.json').write_text('{"pid":42,"created":"100"}', encoding='utf-8')
    return tmp_path


def check(root, *, status='dead', launch=None, now=1000, identity=IDENTITY):
    return recovery.check_once(root, now=now, probe=lambda _: status,
        identity=lambda: identity, launch=launch or (lambda _: pytest.fail('unexpected launch')))


def test_unconfigured_recovery_stays_disabled(tmp_path):
    assert check(tmp_path) == 'disabled'


def test_healthy_exact_owner_is_left_alone(armed):
    assert check(armed, status='alive') == 'healthy'


def test_unverifiable_owner_is_not_treated_as_dead(armed):
    assert check(armed, status='unknown') == 'owner_unverifiable'


def test_explicit_user_stop_survives_periodic_checks(armed):
    (armed / 'run/manager-user-stop').touch()
    for now in (1000, 1060, 2000):
        assert check(armed, now=now) == 'user_stopped'


@pytest.mark.parametrize('identity', [
    {'authenticationId': 'different', 'bootEstimateMs': 1000},
    {'authenticationId': '12345', 'bootEstimateMs': 999999},
])
def test_relogin_or_reboot_does_not_enable_autostart(armed, identity):
    assert check(armed, identity=identity) == 'different_logon'


def test_initial_install_does_not_start_without_an_armed_session(armed):
    (armed / 'run/manager-recovery-armed.json').unlink()
    assert check(armed) == 'not_armed'


def test_retry_limit_survives_new_checker_processes_and_expires(armed):
    calls = []
    launch = lambda root: calls.append(root) or 99
    for now in (1000, 1060, 1120):
        assert check(armed, now=now, launch=launch) == 'recovery_started'
    assert check(armed, now=1180, launch=launch) == 'retry_limit'
    assert len(calls) == 3
    assert check(armed, now=1601, launch=launch) == 'recovery_started'
    assert len(calls) == 4


def test_failed_launch_consumes_attempts_instead_of_spinning(armed):
    def fail(_):
        raise OSError('test launch refusal')
    for now in (1000, 1060, 1120):
        assert check(armed, now=now, launch=fail) == 'launch_failed'
    assert check(armed, now=1180) == 'retry_limit'


def test_corrupt_counter_does_not_reset_the_limit(armed):
    (armed / 'run/manager-recovery-state.json').write_text('bad json', encoding='utf-8')
    assert check(armed) == 'invalid_state'


def test_missing_owner_record_after_fatal_shutdown_is_recoverable(armed):
    (armed / 'run/manager-session.json').unlink()
    assert check(armed, launch=lambda _: 99) == 'recovery_started'


def test_stop_arriving_during_owner_probe_wins(armed):
    def probe(_):
        (armed / 'run/manager-user-stop').touch()
        return 'dead'
    assert recovery.check_once(armed, now=1000, probe=probe,
        identity=lambda: IDENTITY, launch=lambda _: pytest.fail('stop must win')) == 'user_stopped'


def test_attempt_is_durable_before_process_creation(armed):
    def launch(root):
        state = json.loads((root / 'run/manager-recovery-state.json').read_text(encoding='utf-8'))
        assert state['attempts'] == [1000]
        return 99
    assert check(armed, launch=launch) == 'recovery_started'


def test_access_denied_does_not_trigger_duplicate_manager(monkeypatch):
    class Kernel:
        def OpenProcess(self, *args):
            return None
    monkeypatch.setattr(recovery, '_win32', lambda: Kernel())
    monkeypatch.setattr(recovery.ctypes, 'get_last_error', lambda: 5)
    assert recovery._probe_owner({'pid': 42, 'created': '100'}) == 'unknown'

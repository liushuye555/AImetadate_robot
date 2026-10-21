"""One-shot Windows task: recover a missing manager, respecting explicit stops.

No configuration, QQ credentials, AI providers, or message data are loaded here.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .manager_owner import _win32, _creation, _valid_pid, _valid_created, WAIT_TIMEOUT

MAX_ATTEMPTS = 3
WINDOW_SECONDS = 600


def _logon_identity() -> dict:
    kernel = _win32()
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError('Cannot identify interactive logon')
    try:
        stats = ctypes.create_string_buffer(64)
        size = wintypes.DWORD()
        if not advapi.GetTokenInformation(token, 10, stats, len(stats), ctypes.byref(size)):
            raise OSError('Cannot read interactive logon')
        # TOKEN_STATISTICS starts with TokenId and AuthenticationId (two LUIDs).
        authentication = ctypes.c_uint64.from_buffer(stats, 8).value
    finally:
        kernel.CloseHandle(token)
    kernel.GetTickCount64.restype = ctypes.c_uint64
    return {'authenticationId': str(authentication),
            'bootEstimateMs': int(time.time() * 1000) - kernel.GetTickCount64()}


def arm_current_logon(root: Path) -> bool:
    root = Path(root)
    policy = root / 'run/manager-recovery-policy.json'
    if not policy.exists() or _read(policy).get('enabled') is not True:
        return False
    owner_file = root / 'run/manager-session.json'
    if not owner_file.exists() or _probe_owner(_read(owner_file)) != 'alive':
        return False
    _write(root / 'run/manager-recovery-armed.json', _logon_identity())
    return True


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('invalid recovery record')
    return value


def _probe_owner(record: dict) -> str:
    if not _valid_pid(record.get('pid')) or not _valid_created(record.get('created')):
        return 'unknown'
    kernel = _win32()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, record['pid'])
    if not handle:
        # Access denied is not proof that an elevated manager is absent.
        return 'unknown' if ctypes.get_last_error() == 5 else 'dead'
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        if state == WAIT_TIMEOUT:
            token = _creation(kernel, handle)
            return 'unknown' if token is None else ('alive' if token == record['created'] else 'dead')
        return 'dead' if state == 0 else 'unknown'
    finally:
        kernel.CloseHandle(handle)


def _launch(root: Path) -> int:
    executable = root / 'qq-onebot-manager-qt/build/qq-onebot-manager-qt.exe'
    process = subprocess.Popen([str(executable), '--recover-session'], cwd=str(root),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW)
    return process.pid


def check_once(root: Path, *, now: float | None = None, probe=_probe_owner, launch=_launch,
               identity=_logon_identity) -> str:
    root = Path(root)
    run = root / 'run'
    policy = run / 'manager-recovery-policy.json'
    stop = run / 'manager-user-stop'
    if not policy.exists() or _read(policy).get('enabled') is not True:
        return 'disabled'
    if stop.exists():
        return 'user_stopped'
    try:
        armed = _read(run / 'manager-recovery-armed.json')
        current = identity()
        if (armed.get('authenticationId') != current['authenticationId']
                or abs(armed['bootEstimateMs'] - current['bootEstimateMs']) > 120000):
            return 'different_logon'
    except FileNotFoundError:
        return 'not_armed'
    except (OSError, ValueError, UnicodeError, KeyError, TypeError):
        return 'identity_unverifiable'
    timestamp = time.time() if now is None else now
    owner_file = run / 'manager-session.json'
    try:
        status = probe(_read(owner_file)) if owner_file.exists() else 'missing'
    except (OSError, ValueError, UnicodeError):
        status = 'unknown'
    state_file = run / 'manager-recovery-state.json'
    try:
        state = _read(state_file)
    except FileNotFoundError:
        state = {'attempts': []}
    except (OSError, ValueError, UnicodeError):
        return 'invalid_state'  # A corrupt retry counter must not allow a restart loop.
    attempts = state.get('attempts')
    if (not isinstance(attempts, list) or any(type(t) not in (int, float) for t in attempts)):
        return 'invalid_state'
    attempts = [t for t in attempts if timestamp - WINDOW_SECONDS < t <= timestamp]

    def finish(event: str, **fields) -> str:
        # Only transitions and recovery actions are logged, not every healthy tick.
        if state.get('lastEvent') != event or event in ('recovery_started', 'launch_failed'):
            log = root / 'logs/manager-recovery.jsonl'
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'time': timestamp, 'event': event, **fields}) + '\n')
        _write(state_file, {'attempts': attempts, 'lastEvent': event, 'checkedAt': timestamp})
        return event

    if status == 'alive':
        return finish('healthy')
    if status == 'unknown':
        return finish('owner_unverifiable')
    if len(attempts) >= MAX_ATTEMPTS:
        return finish('retry_limit', attempts=len(attempts))
    if stop.exists():
        return 'user_stopped'
    attempts.append(timestamp)
    # Persist before launch, so even an interrupted checker consumes its attempt.
    _write(state_file, {'attempts': attempts, 'lastEvent': 'launching', 'checkedAt': timestamp})
    try:
        pid = launch(root)
    except OSError as error:
        return finish('launch_failed', winerror=getattr(error, 'winerror', None))
    return finish('recovery_started', pid=pid, attempt=len(attempts))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        if '--arm' in sys.argv[1:]:
            return 0 if arm_current_logon(root) else 1
        check_once(root)
        return 0
    except (OSError, ValueError, UnicodeError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

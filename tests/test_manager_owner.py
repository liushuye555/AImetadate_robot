import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from qq_onebot_whitelist import manager_owner as owner


SESSION = "16b1e40b-5321-4ce6-94cd-c169b129b626"
CREATED = "134050640000000001"


class FakeKernel:
    def __init__(self):
        self.closed = []
        self.opened = []
        self.waits = []
        self.created = CREATED
        self.process_available = True
        self.job_available = True
        self.member = True
        self.membership_ok = True
        self.times_ok = True

    def OpenProcess(self, access, inherit, pid):
        self.opened.append(("process", access, inherit, pid))
        return 101 if self.process_available else 0

    def WaitForSingleObject(self, handle, timeout):
        assert handle == 101 and timeout == 0
        return self.waits.pop(0) if self.waits else owner.WAIT_TIMEOUT

    def GetProcessTimes(self, handle, created, exited, kernel, user):
        assert handle == 101
        created._obj.dwLowDateTime = int(self.created) & 0xFFFFFFFF
        created._obj.dwHighDateTime = int(self.created) >> 32
        return self.times_ok

    def OpenJobObjectW(self, access, inherit, name):
        self.opened.append(("job", access, inherit, name))
        return 202 if self.job_available else 0

    def GetCurrentProcess(self):
        return -1

    def IsProcessInJob(self, process, job, member):
        assert process == -1 and job == 202
        member._obj.value = self.member
        return self.membership_ok

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


@pytest.fixture
def managed(tmp_path, monkeypatch):
    record = {"pid": 123, "created": CREATED, "session": SESSION, "job": "Local\\qq-test-manager"}
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "manager-session.json").write_text(json.dumps(record), encoding="utf-8")
    for key, value in record.items():
        monkeypatch.setenv("QQ_ONEBOT_MANAGER_" + key.upper(), str(value))
    kernel = FakeKernel()
    monkeypatch.setattr(owner, "_win32", lambda: kernel)
    return tmp_path, record, kernel


def test_manager_requires_specific_job_and_closes_both_handles(managed):
    root, record, kernel = managed
    assert owner.require_manager(root) == record
    assert kernel.opened == [
        ("process", owner.PROCESS_QUERY_LIMITED_INFORMATION | owner.SYNCHRONIZE, False, 123),
        ("job", owner.JOB_OBJECT_QUERY, False, record["job"]),
    ]
    assert kernel.closed == [202, 101]


@pytest.mark.parametrize("field", ["pid", "created", "session", "job"])
@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_mismatched_environment_refused_before_native_calls(managed, monkeypatch, field, missing):
    root, _, kernel = managed
    name = "QQ_ONEBOT_MANAGER_" + field.upper()
    if missing:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, "wrong")
    with pytest.raises(RuntimeError, match="请通过管理器启动"):
        owner.require_manager(root)
    assert kernel.opened == []


@pytest.mark.parametrize("record", [None, [], {}, {"pid": True}, "broken-json"])
def test_missing_or_invalid_session_record_refused(managed, record):
    root, _, kernel = managed
    path = root / "run" / "manager-session.json"
    if record is None:
        path.unlink()
    else:
        path.write_text("{" if record == "broken-json" else json.dumps(record), encoding="utf-8")
    assert owner.managed_context(root) is False
    assert kernel.opened == []


@pytest.mark.parametrize("field,value", [
    ("pid", True), ("pid", -1), ("pid", 2**32),
    ("created", 123), ("created", "01"), ("created", "-1"),
    ("created", "9" * 5000), ("created", str(2**64)),
    ("session", "not-uuid"), ("job", ""), ("job", "name\0suffix"),
])
def test_invalid_record_fields_fail_closed(managed, monkeypatch, field, value):
    root, record, kernel = managed
    record[field] = value
    (root / "run" / "manager-session.json").write_text(json.dumps(record), encoding="utf-8")
    if "\0" not in str(value):
        monkeypatch.setenv("QQ_ONEBOT_MANAGER_" + field.upper(), str(value))
    assert owner.managed_context(root) is False
    assert kernel.opened == []


@pytest.mark.parametrize("condition,closed", [
    ("unavailable", []), ("exited", [101]), ("wait-failed", [101]),
    ("reused", [101]), ("times-failed", [101]), ("missing-job", [101]),
    ("outside-job", [202, 101]), ("membership-failed", [202, 101]),
    ("exit-during-check", [202, 101]),
])
def test_stale_owner_and_wrong_job_fail_closed_with_handle_cleanup(managed, condition, closed):
    root, _, kernel = managed
    if condition == "unavailable":
        kernel.process_available = False
    elif condition == "exited":
        kernel.waits = [0]
    elif condition == "wait-failed":
        kernel.waits = [0xFFFFFFFF]
    elif condition == "reused":
        kernel.created = str(int(CREATED) + 1)
    elif condition == "times-failed":
        kernel.times_ok = False
    elif condition == "missing-job":
        kernel.job_available = False
    elif condition == "outside-job":
        kernel.member = False
    elif condition == "membership-failed":
        kernel.membership_ok = False
    elif condition == "exit-during-check":
        kernel.waits = [owner.WAIT_TIMEOUT, 0]
    assert owner.managed_context(root) is False
    assert kernel.closed == closed


def test_native_error_during_membership_closes_all_handles(managed, monkeypatch):
    root, _, kernel = managed
    def fail(*args):
        raise OSError("native query failed")
    monkeypatch.setattr(kernel, "IsProcessInJob", fail)
    with pytest.raises(RuntimeError, match="请通过管理器启动"):
        owner.require_manager(root)
    assert kernel.closed == [202, 101]


def test_managed_context_does_not_swallow_programming_errors(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("implementation bug")
    monkeypatch.setattr(owner, "require_manager", fail)
    with pytest.raises(RuntimeError, match="implementation bug"):
        owner.managed_context(tmp_path)


def test_unsupported_platform_refuses_even_with_complete_session(managed, monkeypatch):
    root, _, _ = managed
    monkeypatch.undo()
    monkeypatch.setattr(owner, "sys", SimpleNamespace(platform="unsupported"))
    record = json.loads((root / "run" / "manager-session.json").read_text(encoding="utf-8"))
    for key, value in record.items():
        monkeypatch.setenv("QQ_ONEBOT_MANAGER_" + key.upper(), str(value))
    with pytest.raises(RuntimeError, match="请通过管理器启动"):
        owner.require_manager(root)
    assert owner.process_identity(123) is None


def test_process_identity_preserves_full_filetime_and_closes_handle(managed):
    _, _, kernel = managed
    assert owner.process_identity(123) == CREATED
    assert owner.is_process_alive(123, CREATED)
    assert not owner.is_process_alive(123, str(int(CREATED) + 1))
    assert kernel.closed == [101, 101, 101]


@pytest.mark.parametrize("pid", [None, True, 0, -1, 2**32, "123"])
def test_invalid_pid_never_opens_process(managed, pid):
    _, _, kernel = managed
    assert owner.process_identity(pid) is None
    assert kernel.opened == []


def test_process_exiting_while_identity_read_is_rejected(managed):
    _, _, kernel = managed
    kernel.waits = [owner.WAIT_TIMEOUT, 0]
    assert owner.process_identity(123) is None
    assert kernel.closed == [101]


def test_bot_owner_atomic_record_and_expected_session(managed, monkeypatch):
    root, _, kernel = managed
    owner.save_bot_owner(root, 456, SESSION)
    path = root / "run" / "bot-owner.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"pid": 456, "created": CREATED, "session": SESSION}
    assert list(path.parent.glob("*.tmp")) == []
    assert owner.read_owned_bot(root) == 456
    assert owner.read_owned_bot(root, "00000000-0000-0000-0000-000000000001") is None
    monkeypatch.delenv("QQ_ONEBOT_MANAGER_SESSION")
    assert owner.read_owned_bot(root) is None
    assert owner.read_owned_bot(root, SESSION) == 456
    kernel.created = str(int(CREATED) + 1)
    assert owner.read_owned_bot(root, SESSION) is None


def test_bot_owner_missing_malformed_or_legacy_pid_is_not_trusted(managed):
    root, _, _ = managed
    assert owner.read_owned_bot(root) is None
    path = root / "run" / "bot-owner.json"
    for value in [123, {"pid": 123}, {"pid": 123, "created": CREATED},
                  {"pid": True, "created": CREATED, "session": SESSION}]:
        path.write_text(json.dumps(value), encoding="utf-8")
        assert owner.read_owned_bot(root) is None


def test_failed_bot_owner_replace_preserves_record_and_cleans_temp(managed, monkeypatch):
    root, _, _ = managed
    owner.save_bot_owner(root, 123, SESSION)
    path = root / "run" / "bot-owner.json"
    before = path.read_bytes()
    def fail(*args):
        raise OSError("replace denied")
    monkeypatch.setattr(owner.os, "replace", fail)
    with pytest.raises(OSError, match="replace denied"):
        owner.save_bot_owner(root, 456, SESSION)
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.tmp")) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows Job smoke test")
def test_real_windows_job_guard_in_isolated_process(tmp_path):
    # Only this disposable subprocess joins the temporary Job; pytest itself and
    # all production files/processes remain outside this smoke test's state.
    script = r'''
import ctypes, json, os, pathlib, subprocess, sys, uuid
from ctypes import wintypes
from qq_onebot_whitelist.manager_owner import process_identity
root = pathlib.Path(sys.argv[1])
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel.CreateJobObjectW.restype = wintypes.HANDLE
kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel.AssignProcessToJobObject.restype = wintypes.BOOL
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
session = str(uuid.uuid4())
name = "Local\\qq-onebot-owner-smoke-" + session
job = kernel.CreateJobObjectW(None, name)
assert job, ctypes.get_last_error()
try:
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        print("JOB_UNAVAILABLE", ctypes.get_last_error())
        sys.exit(77)
    record = dict(pid=os.getpid(), created=process_identity(os.getpid()), session=session, job=name)
    (root / "run").mkdir()
    (root / "run" / "manager-session.json").write_text(json.dumps(record), encoding="utf-8")
    env = os.environ.copy()
    env.update({"QQ_ONEBOT_MANAGER_" + key.upper(): str(value) for key, value in record.items()})
    code = "from pathlib import Path; from qq_onebot_whitelist.manager_owner import require_manager; import sys; assert require_manager(Path(sys.argv[1]))['session'] == sys.argv[2]"
    child = subprocess.run([sys.executable, "-c", code, str(root), session], env=env, capture_output=True, text=True, timeout=20)
    assert child.returncode == 0, child.stdout + child.stderr
finally:
    kernel.CloseHandle(job)
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    if result.returncode == 77 and "JOB_UNAVAILABLE" in result.stdout:
        pytest.skip("Host policy prevents the isolated smoke process joining a nested Job")
    assert result.returncode == 0, result.stdout + result.stderr


class TreeKernel:
    def __init__(self):
        # entry: creation token, parent PID; 50 is an unrelated older process
        # whose stale parent PID happens to match the verified root.
        self.processes = {10: (100, 1), 20: (110, 10), 30: (120, 20),
                          40: (130, 999), 50: (90, 10), 60: (140, 40)}
        self.opened = []
        self.closed = []
        self.terminated = []
        self.dead = set()
        self.denied = set()
        self.fail_terminate = set()
        self.fail_wait = set()

    def OpenProcess(self, access, inherit, pid):
        assert access == owner.PROCESS_QUERY_LIMITED_INFORMATION | owner.SYNCHRONIZE | owner.PROCESS_TERMINATE
        assert not inherit
        self.opened.append(pid)
        return 0 if pid in self.denied else 1000 + pid

    def GetProcessTimes(self, handle, created, *args):
        token = self.processes[handle - 1000][0]
        created._obj.dwLowDateTime = token & 0xFFFFFFFF
        created._obj.dwHighDateTime = token >> 32
        return True

    def WaitForSingleObject(self, handle, timeout):
        if handle - 1000 in self.fail_wait:
            return 0xFFFFFFFF
        return owner.WAIT_OBJECT_0 if handle - 1000 in self.dead else owner.WAIT_TIMEOUT

    def TerminateProcess(self, handle, code):
        pid = handle - 1000
        assert code == 1
        # All three target handles must already be held before the first kill.
        assert {10, 20, 30}.issubset(self.opened)
        assert not self.closed
        self.terminated.append(pid)
        if pid in self.fail_terminate:
            return False
        self.dead.add(pid)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle - 1000)
        return True


@pytest.fixture
def tree_kernel(monkeypatch):
    kernel = TreeKernel()
    monkeypatch.setattr(owner, "_win32", lambda: kernel)
    monkeypatch.setattr(owner, "_snapshot_processes", lambda native: (
        200, [(pid, parent) for pid, (_, parent) in kernel.processes.items()]))
    monkeypatch.setattr(owner.ctypes, "get_last_error", lambda: 5, raising=False)
    return kernel


def test_tree_termination_holds_exact_handles_and_stops_descendants_first(tree_kernel):
    kernel = tree_kernel
    assert owner.terminate_process_tree(10, "100")
    assert kernel.terminated == [30, 20, 10]
    assert set(kernel.opened) == {10, 20, 30, 50}
    assert sorted(kernel.closed) == sorted(kernel.opened)
    assert not set(kernel.terminated) & {40, 50, 60}


@pytest.mark.parametrize("pid,created", [(10, "101"), (10, "not-filetime"),
                                         (0, "100"), (True, "100"), (os.getpid(), "100")])
def test_tree_wrong_identity_or_self_never_terminates(tree_kernel, pid, created):
    assert not owner.terminate_process_tree(pid, created)
    assert tree_kernel.terminated == []
    assert tree_kernel.closed == tree_kernel.opened


def test_tree_snapshot_error_stops_nothing_and_closes_root(tree_kernel, monkeypatch):
    def fail(kernel):
        raise OSError("snapshot denied")
    monkeypatch.setattr(owner, "_snapshot_processes", fail)
    assert not owner.terminate_process_tree(10, "100")
    assert tree_kernel.terminated == []
    assert tree_kernel.closed == [10]


@pytest.mark.parametrize("first_ok,last_error,expected", [
    (True, 18, [(10, 1)]), (False, 5, None), (True, 5, None),
])
def test_native_process_snapshot_always_closes_its_handle(monkeypatch, first_ok, last_error, expected):
    closed = []
    def now(value):
        value._obj.dwLowDateTime = 500
        value._obj.dwHighDateTime = 1
    def first(snapshot, entry):
        assert snapshot == 999
        assert entry._obj.dwSize == owner.ctypes.sizeof(owner._ProcessEntry)
        entry._obj.th32ProcessID = 10
        entry._obj.th32ParentProcessID = 1
        return first_ok
    kernel = SimpleNamespace(
        GetSystemTimeAsFileTime=now,
        CreateToolhelp32Snapshot=lambda flags, pid: 999,
        Process32FirstW=first,
        Process32NextW=lambda *args: False,
        CloseHandle=lambda handle: closed.append(handle),
    )
    monkeypatch.setattr(owner.ctypes, "get_last_error", lambda: last_error, raising=False)
    if expected is None:
        with pytest.raises(OSError):
            owner._snapshot_processes(kernel)
    else:
        assert owner._snapshot_processes(kernel) == ((1 << 32) | 500, expected)
    assert closed == [999]


def test_tree_descendant_access_denied_stops_nothing(tree_kernel):
    tree_kernel.denied.add(30)
    assert not owner.terminate_process_tree(10, "100")
    assert tree_kernel.terminated == []
    assert sorted(tree_kernel.closed) == [10, 20]


def test_tree_missing_intermediate_parent_with_live_children_refuses_partial_cleanup(tree_kernel, monkeypatch):
    tree_kernel.denied.add(20)
    monkeypatch.setattr(owner.ctypes, "get_last_error", lambda: 87)
    assert not owner.terminate_process_tree(10, "100")
    assert tree_kernel.terminated == []
    assert tree_kernel.closed == [10]


def test_tree_terminate_failure_does_not_orphan_children_by_killing_parent(tree_kernel):
    tree_kernel.fail_terminate.add(30)
    assert not owner.terminate_process_tree(10, "100")
    assert tree_kernel.terminated == [30]
    assert sorted(tree_kernel.closed) == sorted(tree_kernel.opened)


def test_tree_wait_failure_stops_nothing(tree_kernel):
    tree_kernel.fail_wait.add(30)
    assert not owner.terminate_process_tree(10, "100")
    assert tree_kernel.terminated == []
    assert sorted(tree_kernel.closed) == sorted(tree_kernel.opened)


def test_tree_candidate_reused_after_snapshot_requires_fresh_parent_map(tree_kernel, monkeypatch):
    kernel = tree_kernel
    kernel.processes[20] = (250, 999)  # Snapshot used to have parent 10.
    kernel.processes[30] = (260, 20)
    snapshots = iter([
        (200, [(10, 1), (20, 10), (30, 20)]),
        (300, [(10, 1), (20, 999), (30, 20)]),
    ])
    monkeypatch.setattr(owner, "_snapshot_processes", lambda native: next(snapshots))
    # This test's only legitimate target is the root.
    def terminate(handle, code):
        kernel.terminated.append(handle - 1000)
        kernel.dead.add(handle - 1000)
        return True
    monkeypatch.setattr(kernel, "TerminateProcess", terminate)
    assert owner.terminate_process_tree(10, "100")
    assert kernel.terminated == [10]
    assert sorted(kernel.closed) == sorted(kernel.opened)


def test_tree_new_descendant_is_collected_before_any_termination(tree_kernel, monkeypatch):
    kernel = tree_kernel
    snapshots = iter([
        (200, [(10, 1), (20, 10)]),
        (200, [(10, 1), (20, 10), (30, 20)]),
        (200, [(10, 1), (20, 10), (30, 20)]),
    ])
    monkeypatch.setattr(owner, "_snapshot_processes", lambda native: next(snapshots))
    assert owner.terminate_process_tree(10, "100")
    assert kernel.terminated == [30, 20, 10]


def test_owned_tree_requires_exact_session_and_passes_creation_token(tmp_path, monkeypatch):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "bot-owner.json").write_text(
        json.dumps({"pid": 10, "created": "100", "session": SESSION}), encoding="utf-8")
    calls = []
    def terminate(pid, created):
        calls.append((pid, created))
        return True
    monkeypatch.setattr(owner, "terminate_process_tree", terminate)
    assert not owner.terminate_owned_tree(tmp_path, "00000000-0000-0000-0000-000000000001")
    assert not owner.terminate_owned_tree(tmp_path, "invalid")
    assert calls == []
    assert owner.terminate_owned_tree(tmp_path, SESSION)
    assert calls == [(10, "100")]


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows process-tree smoke test")
def test_real_windows_exact_handle_tree_cleanup_including_venv_launcher(tmp_path):
    # A disposable Python parent starts a disposable Python child. sys.executable
    # intentionally preserves the Windows venv launcher layer when one exists.
    # No service entrypoint, production state, or network is involved.
    child_ready = tmp_path / "child-ready.json"
    parent_ready = tmp_path / "parent-ready.json"
    child_code = "import json,os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid()})); time.sleep(30)"
    parent_code = r'''
import json, os, pathlib, subprocess, sys, time
from qq_onebot_whitelist.manager_owner import process_identity
child = subprocess.Popen([sys.executable, "-c", sys.argv[3], sys.argv[2]])
pathlib.Path(sys.argv[1]).write_text(json.dumps({"pid": os.getpid(), "created": process_identity(os.getpid()),
    "child": child.pid, "childCreated": process_identity(child.pid)}))
time.sleep(30)
'''
    kernel = owner._win32()
    parent = subprocess.Popen([sys.executable, "-c", parent_code, str(parent_ready), str(child_ready), child_code],
                              cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handles = []
    records = []
    root_created = owner.process_identity(parent.pid)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                record = json.loads(parent_ready.read_text())
                child_record = json.loads(child_ready.read_text())
                break
            except (OSError, ValueError):
                time.sleep(0.01)
        else:
            pytest.fail("Disposable parent/child did not become ready")
        records = [(parent.pid, root_created), (record["pid"], record["created"]),
                   (record["child"], record["childCreated"]),
                   (child_record["pid"], owner.process_identity(child_record["pid"]))]
        for pid, created in records:
            assert created is not None
            handle = kernel.OpenProcess(owner.SYNCHRONIZE | owner.PROCESS_QUERY_LIMITED_INFORMATION
                                        | owner.PROCESS_TERMINATE, False, pid)
            assert handle
            handles.append(handle)
            assert owner._creation(kernel, handle) == created
        assert not owner.terminate_process_tree(parent.pid, str(int(root_created) + 1))
        assert all(kernel.WaitForSingleObject(handle, 0) == owner.WAIT_TIMEOUT for handle in handles)
        assert owner.terminate_process_tree(parent.pid, root_created)
        assert all(kernel.WaitForSingleObject(handle, 0) == owner.WAIT_OBJECT_0 for handle in handles)
        parent.wait(timeout=5)
    finally:
        # Assertion failures also clean up by original handles or verified root
        # identity. Never use taskkill or an unchecked PID for this cleanup.
        if root_created is not None:
            owner.terminate_process_tree(parent.pid, root_created)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) == owner.WAIT_TIMEOUT:
                kernel.TerminateProcess(handle, 99)
                kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)
        if parent.poll() is None:
            parent.kill()  # Popen retains the exact original process HANDLE.
        parent.wait(timeout=5)

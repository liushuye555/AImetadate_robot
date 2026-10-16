"""Fail-closed Windows manager ownership and PID identity checks.

The named Job belongs to the Qt manager. Never retain a Job handle here: its
last handle closing is what lets Windows end the manager's child processes.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
JOB_OBJECT_QUERY = 0x0004
WAIT_TIMEOUT = 258
WAIT_OBJECT_0 = 0
PROCESS_TERMINATE = 0x0001
TH32CS_SNAPPROCESS = 0x00000002
_ENV_PREFIX = "QQ_ONEBOT_MANAGER_"
_FIELDS = ("pid", "created", "session", "job")


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class ManagerRequiredError(RuntimeError):
    """Expected refusal when this process has no valid manager owner."""


def _refuse() -> ManagerRequiredError:
    return ManagerRequiredError("请通过管理器启动：管理器会话已失效或当前进程不属于管理器。")


def _win32():
    if sys.platform != "win32":
        raise _refuse()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetProcessTimes": ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "GetSystemTimeAsFileTime": ([ctypes.POINTER(wintypes.FILETIME)], None),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
        "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = args
        function.restype = result
    return kernel


def _valid_pid(pid) -> bool:
    return type(pid) is int and 0 < pid <= 0xFFFFFFFF


def _valid_created(value) -> bool:
    return (
        isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal()
        and 0 < int(value) <= 0xFFFFFFFFFFFFFFFF and str(int(value)) == value
    )


def _valid_session(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _creation(kernel, handle) -> str | None:
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        return None
    return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)


def process_identity(pid: int) -> str | None:
    """Return the live process's native creation FILETIME, never a PID alone."""
    if not _valid_pid(pid):
        return None
    try:
        kernel = _win32()
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            return None
        try:
            if kernel.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
                return None
            created = _creation(kernel, handle)
            if kernel.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
                return None
            return created if _valid_created(created) else None
        finally:
            kernel.CloseHandle(handle)
    except (ManagerRequiredError, OSError):
        return None


def is_process_alive(pid: int, created: str | None = None) -> bool:
    """Probe without sending signals; optionally reject a reused PID."""
    if created is not None and not _valid_created(created):
        return False
    identity = process_identity(pid)
    return identity is not None and (created is None or identity == created)


def _read_record(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def require_manager(repo_root: Path) -> dict:
    """Require the exact live manager session and membership of its named Job."""
    record = _read_record(Path(repo_root) / "run" / "manager-session.json")
    if (
        record is None or set(record) != set(_FIELDS)
        or not _valid_pid(record.get("pid"))
        or not _valid_created(record.get("created"))
        or not _valid_session(record.get("session"))
        or not isinstance(record.get("job"), str) or not record["job"]
        or "\0" in record["job"]
    ):
        raise _refuse()
    if any(os.environ.get(_ENV_PREFIX + field.upper()) != str(record[field]) for field in _FIELDS):
        raise _refuse()
    try:
        kernel = _win32()
        owner = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, record["pid"])
        if not owner:
            raise _refuse()
        try:
            if kernel.WaitForSingleObject(owner, 0) != WAIT_TIMEOUT or _creation(kernel, owner) != record["created"]:
                raise _refuse()
            job = kernel.OpenJobObjectW(JOB_OBJECT_QUERY, False, record["job"])
            if not job:
                raise _refuse()
            try:
                member = wintypes.BOOL()
                if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), job, ctypes.byref(member)) or not member.value:
                    raise _refuse()
            finally:
                kernel.CloseHandle(job)
            if kernel.WaitForSingleObject(owner, 0) != WAIT_TIMEOUT:
                raise _refuse()
        finally:
            kernel.CloseHandle(owner)
    except OSError as error:
        raise _refuse() from error
    return record


def managed_context(repo_root: Path) -> bool:
    """Return whether the current process is managed, without launching anything."""
    try:
        require_manager(repo_root)
    except ManagerRequiredError:
        return False
    return True


def save_bot_owner(repo_root: Path, pid: int, session: str) -> None:
    """Atomically record an already launched bot with its non-reusable identity."""
    if not _valid_session(session):
        raise _refuse()
    created = process_identity(pid)
    if created is None:
        raise _refuse()
    target = Path(repo_root) / "run" / "bot-owner.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix="bot-owner-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump({"pid": pid, "created": created, "session": session}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def read_owned_bot(repo_root: Path, session: str | None = None) -> int | None:
    """Read only a live bot from the expected session, rejecting reused PIDs."""
    expected = session if session is not None else os.environ.get(_ENV_PREFIX + "SESSION")
    if not _valid_session(expected):
        return None
    record = _read_record(Path(repo_root) / "run" / "bot-owner.json")
    if (
        record is None or set(record) != {"pid", "created", "session"}
        or record.get("session") != expected or not _valid_pid(record.get("pid"))
        or not _valid_created(record.get("created"))
    ):
        return None
    return record["pid"] if is_process_alive(record["pid"], record["created"]) else None


def _snapshot_processes(kernel) -> tuple[int, list[tuple[int, int]]]:
    """Take a Toolhelp parent map with a creation-time cutoff against PID reuse."""
    now = wintypes.FILETIME()
    kernel.GetSystemTimeAsFileTime(ctypes.byref(now))
    cutoff = (now.dwHighDateTime << 32) | now.dwLowDateTime
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, 0, -1, ctypes.c_void_p(-1).value):
        raise OSError("Cannot inspect process descendants")
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        entries = []
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        if not available:
            raise OSError("Cannot read process snapshot")
        while available:
            entries.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise OSError("Cannot finish reading process snapshot")
        return cutoff, entries
    finally:
        kernel.CloseHandle(snapshot)


def terminate_process_tree(pid: int, created: str) -> bool:
    """Terminate a verified process tree through retained HANDLEs, children first.

    Return False on an unverified root, incomplete enumeration, access failure,
    or unsuccessful termination. Collection failures terminate nothing. Retained
    handles and FILETIME comparisons prevent stale Toolhelp parent PIDs or reused
    PIDs from selecting unrelated processes. The manager Job remains the final
    lifetime guarantee for processes which continuously spawn during shutdown.
    """
    if not _valid_pid(pid) or pid == os.getpid() or not _valid_created(created):
        return False
    handles = []
    try:
        kernel = _win32()
        access = PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE
        root = kernel.OpenProcess(access, False, pid)
        if not root:
            return False
        handles.append(root)
        if _creation(kernel, root) != created:
            return False
        if kernel.WaitForSingleObject(root, 0) not in (WAIT_TIMEOUT, WAIT_OBJECT_0):
            return False
        # Each selected parent remains open throughout collection and termination.
        # Windows cannot recycle its PID while this exact process object is held.
        selected = {pid: (root, int(created), 0)}
        ignored = set()
        for _ in range(8):
            cutoff, entries = _snapshot_processes(kernel)
            discovered = False
            retry = False
            pending = entries
            while pending:
                remaining = []
                progressed = False
                for child_pid, parent_pid in pending:
                    if child_pid in selected or child_pid in ignored:
                        continue
                    if parent_pid not in selected:
                        remaining.append((child_pid, parent_pid))
                        continue
                    if not _valid_pid(child_pid) or child_pid == os.getpid():
                        return False
                    child = kernel.OpenProcess(access, False, child_pid)
                    if not child:
                        # A process which vanished during enumeration is harmless;
                        # denied access prevents us claiming a complete cleanup.
                        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER
                            if any(ancestor_pid == child_pid for _, ancestor_pid in entries):
                                # Its own children may be orphaned already, but
                                # their ancestry cannot be proved without this
                                # parent's creation identity. Refuse partial work.
                                return False
                            ignored.add(child_pid)
                            continue
                        return False
                    handles.append(child)
                    token = _creation(kernel, child)
                    state = kernel.WaitForSingleObject(child, 0)
                    if not _valid_created(token) or state not in (WAIT_TIMEOUT, WAIT_OBJECT_0):
                        return False
                    parent = selected[parent_pid]
                    if int(token) < parent[1]:
                        # The snapshot refers to an older, unrelated incarnation
                        # of this parent PID. Never terminate this candidate.
                        ignored.add(child_pid)
                        continue
                    if int(token) > cutoff:
                        # It may have replaced the snapshot's process. Inspect a
                        # fresh parent map instead of trusting the stale relation.
                        retry = True
                        continue
                    selected[child_pid] = (child, int(token), parent[2] + 1)
                    progressed = discovered = True
                if not progressed:
                    break
                pending = remaining
            if not discovered and not retry:
                break
        else:
            return False

        for handle, _, _ in sorted(selected.values(), key=lambda item: item[2], reverse=True):
            state = kernel.WaitForSingleObject(handle, 0)
            if state == WAIT_OBJECT_0:
                continue
            if state != WAIT_TIMEOUT:
                return False
            if not kernel.TerminateProcess(handle, 1):
                if kernel.WaitForSingleObject(handle, 0) != WAIT_OBJECT_0:
                    return False
            if kernel.WaitForSingleObject(handle, 5000) != WAIT_OBJECT_0:
                return False
        return True
    except (ManagerRequiredError, OSError):
        return False
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def terminate_owned_tree(repo_root: Path, session: str) -> bool:
    """Stop only the bot record belonging to the explicit manager session."""
    if not _valid_session(session):
        return False
    record = _read_record(Path(repo_root) / "run" / "bot-owner.json")
    if (
        record is None or set(record) != {"pid", "created", "session"}
        or record.get("session") != session or not _valid_pid(record.get("pid"))
        or not _valid_created(record.get("created"))
    ):
        return False
    return terminate_process_tree(record["pid"], record["created"])

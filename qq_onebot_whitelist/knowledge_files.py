"""Safe, content-addressed local archive for eligible group files."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable

from .file_sync import FileTooLargeError, download_to_staging

_LOCK = threading.RLock()
_TEMP_NAME = ".knowledge-tmp"
_LOCK_NAME = ".knowledge-files.lock"
_MIN_FREE_BYTES = 64 * 1024 * 1024
_SCOPE_RE = re.compile(r"^group:\d+$")
_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,16}$")
_OPAQUE_ONEBOT_FILE_ID_RE = re.compile(
    r"^/(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"
    r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\})$",
    re.IGNORECASE,
)


def _result(status: str, *, name: str = "", sha256: str = "", path: str = "",
            size: int | None = None, error: str = "") -> dict:
    out = {"status": status}
    if sha256:
        out["sha256"] = sha256
    if path:
        out["path"] = path
    if size is not None:
        out["size"] = size
    if name:
        out["name"] = name
    if error:
        out["error"] = error
    return out


def _archive_size(root: Path, temp_dir: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        if (not item.is_file() or item == temp_dir or temp_dir in item.parents or
                item.name == _LOCK_NAME):
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def _find_hash(root: Path, digest: str) -> Path | None:
    # Accept both digest-only legacy entries and digest-plus-extension entries,
    # but never trust the filename without verifying the bytes.
    candidates = [root / digest, *root.glob(digest + ".*")]
    for item in candidates:
        if not item.is_file():
            continue
        check = hashlib.sha256()
        try:
            with item.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    check.update(block)
        except OSError:
            continue
        if check.hexdigest() == digest:
            return item
    return None


def _extension(name: str) -> str:
    suffix = Path(name).suffix
    return suffix.lower() if _EXT_RE.fullmatch(suffix) else ""


def _pid_state(pid: int) -> bool | None:
    """Return alive/dead, or None when the platform cannot determine liveness."""
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            from .control import _windows_pid_running
            return _windows_pid_running(pid)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


def archive_file(source: dict, root: Path, *, max_bytes: int, budget_bytes: int,
                 enabled: Callable[[], bool], fetch_url: Callable[[dict], str]) -> dict:
    """Download and archive an eligible group file, returning a compact status record.

    ``fetch_url`` is called only after all cheap validation and the feature switch check.
    Signed URLs are deliberately never included in returned errors.
    """
    source = source if isinstance(source, dict) else {}
    name = str(source.get("file_name") or "")
    scope = str(source.get("scope") or "")
    file_id = source.get("file_id")
    file_id_text = str(file_id).strip() if file_id is not None else ""
    # IDs are opaque, but a URL/path/name is never a valid substitute for one.
    looks_like_url_or_path = ("://" in file_id_text or
                              ("/" in file_id_text and not _OPAQUE_ONEBOT_FILE_ID_RE.fullmatch(file_id_text)) or
                              "\\" in file_id_text or bool(re.search(r"\.[A-Za-z0-9]{1,16}$", file_id_text)))
    if (not _SCOPE_RE.fullmatch(scope) or not file_id_text or
            any(ch.isspace() for ch in file_id_text) or looks_like_url_or_path):
        return _result("failed", name=name, error="InvalidSource")
    try:
        declared_size = source.get("file_size")
        declared_size = None if declared_size is None else int(declared_size)
        if declared_size is not None and declared_size < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return _result("failed", name=name, error="InvalidSize")
    if declared_size == 0:
        return _result("failed", name=name, error="EmptyFile")
    if max_bytes < 1 or budget_bytes < 0:
        return _result("failed", name=name, error="InvalidLimit")

    root = Path(root)
    temp_dir = root / _TEMP_NAME
    stage: Path | None = None
    lock_fd: int | None = None
    with _LOCK:
        try:
            # This must precede even root/temp/lock creation so the disabled path
            # has no filesystem side effects.
            if not enabled():
                return _result("disabled", name=name)

            root.mkdir(parents=True, exist_ok=True)
            if not enabled():
                return _result("disabled", name=name)
            try:
                lock_fd = os.open(root / _LOCK_NAME,
                                  os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                lock_path = root / _LOCK_NAME
                try:
                    owner_text = lock_path.read_text(encoding="ascii").strip()
                    owner_pid = int(owner_text)
                except (OSError, UnicodeError, ValueError, OverflowError):
                    # Empty/invalid content may be the tiny create-before-write
                    # window of a live peer. Never reclaim an ambiguous lock.
                    return _result("skipped", name=name, error="ArchiveBusy")
                if _pid_state(owner_pid) is not False:
                    return _result("skipped", name=name, error="ArchiveBusy")
                try:
                    # Another stale-lock recovery may have replaced it with a
                    # live owner's lock since our first read.
                    if lock_path.read_text(encoding="ascii").strip() != owner_text:
                        return _result("skipped", name=name, error="ArchiveBusy")
                    lock_path.unlink()
                except (OSError, UnicodeError):
                    return _result("skipped", name=name, error="ArchiveBusy")
                try:
                    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    return _result("skipped", name=name, error="ArchiveBusy")
            # Publish ownership immediately. A contender that observes the brief
            # empty-file interval treats it as busy and does not remove it.
            os.write(lock_fd, str(os.getpid()).encode("ascii"))
            os.fsync(lock_fd)
            if not enabled():
                return _result("disabled", name=name)

            occupied = _archive_size(root, temp_dir)
            remaining = budget_bytes - occupied
            # Budget accounting is intentionally conservative: even a possible
            # content duplicate must fit before download, so dedupe never writes
            # beyond the configured archive budget.
            if remaining <= 0 or (declared_size is not None and declared_size > remaining):
                return _result("skipped", name=name, error="BudgetExceeded")
            hard_limit = min(int(max_bytes), remaining)
            if declared_size is not None and declared_size > max_bytes:
                return _result("skipped", name=name, error="FileTooLarge")
            needed = declared_size if declared_size is not None else hard_limit
            probe = root
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            if shutil.disk_usage(probe).free < needed + _MIN_FREE_BYTES:
                return _result("skipped", name=name, error="InsufficientDiskSpace")

            if not enabled():
                return _result("disabled", name=name)
            try:
                url = fetch_url(source)
            except Exception as exc:
                return _result("failed", name=name, error=type(exc).__name__)
            if not enabled():
                return _result("disabled", name=name)
            if not isinstance(url, str) or not url:
                return _result("failed", name=name, error="URLUnavailable")

            temp_dir.mkdir(parents=True, exist_ok=True)
            stage = temp_dir / (uuid.uuid4().hex + ".stage")
            if not enabled():
                return _result("disabled", name=name)
            try:
                download_to_staging(url, stage, max_bytes=hard_limit)
            except FileTooLargeError:
                return _result("skipped", name=name, error="FileTooLarge")
            except Exception as exc:
                return _result("failed", name=name, error=type(exc).__name__)
            if not enabled():
                return _result("disabled", name=name)

            actual_size = stage.stat().st_size
            if actual_size == 0:
                return _result("failed", name=name, error="EmptyFile")
            if actual_size > max_bytes or actual_size > remaining:
                return _result("skipped", name=name, error="LimitExceeded")
            if declared_size is not None and actual_size != declared_size:
                return _result("failed", name=name, error="SizeMismatch")
            digest_obj = hashlib.sha256()
            with stage.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest_obj.update(block)
            digest = digest_obj.hexdigest()
            existing = _find_hash(root, digest)
            if existing is not None:
                return _result("saved", name=name, sha256=digest,
                               path=str(existing.resolve()), size=actual_size)
            # Final switch check is immediately before the atomic promotion.
            if not enabled():
                return _result("disabled", name=name)
            destination = root / (digest + _extension(name))
            if destination.exists():
                return _result("failed", name=name, error="HashPathOccupied")
            # The lock serializes this module's writers; replace is atomic on one volume.
            stage.replace(destination)
            stage = None
            return _result("saved", name=name, sha256=digest,
                           path=str(destination.resolve()), size=actual_size)
        except Exception as exc:
            return _result("failed", name=name, error=type(exc).__name__)
        finally:
            if stage is not None:
                try:
                    stage.unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    stage.with_suffix(stage.suffix + ".part").unlink(missing_ok=True)
                except OSError:
                    pass
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                finally:
                    try:
                        (root / _LOCK_NAME).unlink(missing_ok=True)
                    except OSError:
                        pass

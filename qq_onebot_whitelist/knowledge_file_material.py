"""Prepare bounded, ephemeral file previews for knowledge analysis."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import load_config
from . import knowledge_files
from .file_sync import FileTooLargeError, fetch_download_url_once
from .knowledge_config import group_scope, profile_for
from .knowledge_preview import preview_file

_MAX_FILES = 3
_MAX_FILE_BYTES = 256 * 1024
_MAX_PREVIEW_CHARS = 6000
_MAX_TOTAL_BYTES = 1024 * 1024
_PREVIEWABLE_EXTS = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml",
                     ".toml", ".xml", ".ini", ".log", ".csv", ".zip", ".pdf"}


def prepare_file_previews(config_path: Path, scope: str, records: list[dict]) -> list[dict]:
    """Download and preview at most three opted-in files in temporary storage.

    The caller's records are copied. URLs, paths, and download errors are never
    attached to the returned data. No database or persistent archive is used.
    """
    config_path = Path(config_path)
    scope = group_scope(scope)
    copied = deepcopy(records or [])

    def current_enabled() -> bool:
        fresh = load_config(config_path)
        profile = profile_for(fresh, scope)
        return profile.allows("files") and profile.option_enabled("files", "preview_enabled")

    # Re-read config immediately before any temporary work and again afterwards.
    if not current_enabled():
        return copied
    temp_owner = None
    try:
        temp_owner = TemporaryDirectory(prefix="knowledge-file-preview-")
        root = Path(temp_owner.name) / "archive"
        remaining = _MAX_TOTAL_BYTES
        processed = 0
        for record in copied:
            if not current_enabled():
                break
            if record.get("scope") != scope:
                continue
            for source in record.get("files") or []:
                if processed >= _MAX_FILES or remaining <= 0:
                    break
                if not current_enabled():
                    break
                if not isinstance(source, dict):
                    continue
                file_id = source.get("file_id")
                name = str(source.get("file_name") or source.get("name") or "")
                if not file_id or not name:
                    continue
                suffix = Path(name).suffix.lower()
                if suffix not in _PREVIEWABLE_EXTS:
                    source["preview"] = {
                        "status": "unsupported", "text": "", "format": suffix.lstrip("."),
                        "truncated": False, "error": "UnsupportedFormat",
                    }
                    processed += 1
                    continue
                try:
                    declared_size = source.get("file_size", source.get("size"))
                    declared_size = None if declared_size is None else int(declared_size)
                except (TypeError, ValueError, OverflowError):
                    source["preview"] = {"status": "failed", "text": "", "error": "InvalidSize"}
                    processed += 1
                    continue
                if declared_size is not None and (declared_size < 0 or declared_size > _MAX_FILE_BYTES):
                    source["preview"] = {"status": "too_large", "text": "", "error": "FileTooLarge"}
                    processed += 1
                    continue
                allowed_bytes = min(_MAX_FILE_BYTES, remaining)
                if declared_size is not None:
                    allowed_bytes = min(allowed_bytes, max(declared_size, 1))

                def enabled() -> bool:
                    return current_enabled()

                def fetch_url(file_source: dict) -> str:
                    if not enabled():
                        raise PermissionError("PreviewDisabled")
                    fresh = load_config(config_path)
                    return fetch_download_url_once(
                        scope.split(":", 1)[1], str(file_id), source.get("busid"),
                        ws_url=fresh.onebot_ws_url,
                    )

                try:
                    archived = knowledge_files.archive_file(
                        # archive_file rejects path-like IDs. OneBot may use an
                        # opaque UUID prefixed by '/', so pass a local safe token;
                        # fetch_url above still uses the original API identifier.
                        {**source, "scope": scope, "file_name": name,
                         "file_id": "preview-" + sha256(str(file_id).encode()).hexdigest()},
                        root, max_bytes=allowed_bytes, budget_bytes=remaining,
                        enabled=enabled, fetch_url=fetch_url,
                    )
                    if archived.get("status") != "saved" or not archived.get("path"):
                        source["preview"] = {
                            "status": "too_large" if archived.get("error") in ("FileTooLarge", "LimitExceeded") else "failed",
                            "text": "", "error": str(archived.get("error") or archived.get("status") or "PreviewFailed")[:80],
                        }
                    elif not enabled():
                        break
                    else:
                        saved = Path(archived["path"])
                        actual_size = saved.stat().st_size
                        if actual_size > allowed_bytes or actual_size > remaining:
                            source["preview"] = {"status": "too_large", "text": "", "error": "FileTooLarge"}
                        else:
                            viewed = preview_file(saved, max_bytes=min(_MAX_FILE_BYTES, actual_size or 1),
                                                  max_chars=_MAX_PREVIEW_CHARS)
                            source["preview"] = {
                                "status": viewed["status"], "text": viewed["text"],
                                "format": viewed.get("format", suffix.lstrip(".")),
                                "truncated": viewed.get("truncated", False),
                                "size": actual_size, "sha256": archived.get("sha256", ""),
                            }
                            if viewed.get("error"):
                                source["preview"]["error"] = viewed["error"]
                            remaining -= actual_size
                    processed += 1
                except FileTooLargeError:
                    source["preview"] = {"status": "too_large", "text": "", "error": "FileTooLarge"}
                    processed += 1
                except Exception as exc:
                    source["preview"] = {"status": "failed", "text": "", "error": type(exc).__name__}
                    processed += 1
        return copied
    finally:
        # This fresh read is intentional: if the user disabled previews mid-run,
        # no more files are processed. TemporaryDirectory always removes originals.
        try:
            current_enabled()
        except Exception:
            pass
        if temp_owner is not None:
            temp_owner.cleanup()

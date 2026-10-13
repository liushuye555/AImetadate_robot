"""Bounded, read-only previews for locally staged knowledge files."""
from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from .content_utils import redact_secrets

_TEXT_EXTS = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml",
              ".toml", ".xml", ".ini", ".log", ".csv"}
_BINARY_EXTS = {".model", ".dll", ".so", ".exe", ".safetensors"}
_ARCHIVE_MAX_ENTRIES = 200
_ARCHIVE_MAX_MEMBER = 64 * 1024
_ARCHIVE_PREVIEW_MEMBERS = 3


def _result(status: str, text: str = "", fmt: str = "", truncated: bool = False,
            error: str | None = None) -> dict:
    out = {"status": status, "text": text, "format": fmt, "truncated": truncated}
    if error:
        out["error"] = error
    return out


def _bounded_text(raw: bytes, max_chars: int, fmt: str, *, incomplete: bool = False) -> dict:
    if b"\x00" in raw:
        return _result("unsupported", fmt=fmt, error="BinaryContent")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError:
            if not incomplete:
                return _result("unsupported", fmt=fmt, error="TextDecodeError")
            # The byte limit may split the final multibyte character. Preserve
            # the decodable prefix rather than rejecting otherwise valid text.
            try:
                text = raw.decode("utf-8-sig", errors="ignore")
            except UnicodeDecodeError:
                text = raw.decode("gb18030", errors="ignore")
    if text:
        controls = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t\f\b")
        if controls / len(text) > 0.01:
            return _result("unsupported", fmt=fmt, error="BinaryContent")
    clean = redact_secrets(text)
    truncated = len(clean) > max_chars
    return _result("ready", clean[:max_chars], fmt, truncated)


def _preview_zip(path: Path, max_bytes: int, max_chars: int) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > _ARCHIVE_MAX_ENTRIES:
                return _result("unsupported", fmt="zip", error="TooManyEntries")
            lines = ["ZIP contents:"]
            eligible = []
            for info in infos:
                name = info.filename
                parts = PurePosixPath(name.replace("\\", "/")).parts
                mode = (info.external_attr >> 16) & 0xFFFF
                unsafe = (PurePosixPath(name).is_absolute() or ".." in parts or
                          (len(name) > 1 and name[1] == ":") or stat.S_ISLNK(mode))
                if unsafe:
                    lines.append(f"[skipped unsafe] {PurePosixPath(name).name}")
                    continue
                if info.is_dir():
                    lines.append(f"[dir] {name}")
                    continue
                lines.append(f"[file] {name} ({info.file_size} bytes)")
                if Path(name).suffix.lower() in _TEXT_EXTS:
                    if info.file_size / max(info.compress_size, 1) > 100:
                        lines.append(f"[skipped compression ratio limit] {PurePosixPath(name).name}")
                    elif info.file_size > _ARCHIVE_MAX_MEMBER:
                        lines.append(f"[skipped member size limit] {PurePosixPath(name).name}")
                    else:
                        eligible.append(info)
            total = 0
            for info in eligible[:_ARCHIVE_PREVIEW_MEMBERS]:
                if total + info.file_size > max_bytes:
                    lines.append(f"\n--- {PurePosixPath(info.filename).name}: skipped total size limit ---")
                    continue
                try:
                    with archive.open(info) as member:
                        raw = member.read(min(_ARCHIVE_MAX_MEMBER, max_bytes - total) + 1)
                    if len(raw) > _ARCHIVE_MAX_MEMBER or len(raw) > max_bytes - total:
                        lines.append(f"\n--- {PurePosixPath(info.filename).name}: skipped size limit ---")
                        continue
                    total += len(raw)
                    result = _bounded_text(raw, max_chars, Path(info.filename).suffix.lower())
                    if result["status"] == "ready":
                        lines.append(f"\n--- {PurePosixPath(info.filename).name} ---\n{result['text']}")
                    else:
                        lines.append(f"\n--- {PurePosixPath(info.filename).name}: skipped unsupported content ---")
                except Exception:
                    lines.append(f"\n--- {PurePosixPath(info.filename).name}: skipped unreadable member ---")
            merged = redact_secrets("\n".join(lines))
            truncated = len(merged) > max_chars
            return _result("ready", merged[:max_chars], "zip", truncated)
    except Exception as exc:
        return _result("failed", fmt="zip", error=type(exc).__name__)


def preview_file(path: Path, *, max_bytes: int = 262144, max_chars: int = 6000) -> dict:
    """Preview a local file without executing it or extracting archives."""
    try:
        if max_bytes < 1 or max_chars < 0:
            return _result("failed", error="InvalidLimit")
        target = Path(path)
        suffix = target.suffix.lower()
        size = target.stat().st_size
        if suffix in _BINARY_EXTS:
            return _result("unsupported", fmt=suffix.lstrip("."), error="BinaryFormat")
        if suffix == ".zip":
            if size > max_bytes:
                return _result("too_large", fmt="zip", error="FileTooLarge")
            return _preview_zip(target, max_bytes, max_chars)
        if suffix == ".pdf":
            if size > max_bytes:
                return _result("too_large", fmt="pdf", error="FileTooLarge")
            try:
                from pypdf import PdfReader
            except ImportError:
                return _result("unsupported", fmt="pdf", error="PdfSupportUnavailable")
            try:
                reader = PdfReader(str(target), strict=False)
                pages = []
                for i, page in enumerate(reader.pages[:3], 1):
                    pages.append(f"[Page {i}]\n{page.extract_text() or ''}")
                return _bounded_text("\n\n".join(pages).encode("utf-8"), max_chars, "pdf")
            except Exception as exc:
                return _result("failed", fmt="pdf", error=type(exc).__name__)
        if suffix not in _TEXT_EXTS:
            return _result("unsupported", fmt=suffix.lstrip("."), error="UnsupportedFormat")
        with target.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        truncated_bytes = len(raw) > max_bytes
        raw = raw[:max_bytes]
        result = _bounded_text(raw, max_chars, suffix.lstrip("."), incomplete=truncated_bytes)
        if result["status"] == "ready" and truncated_bytes:
            result["truncated"] = True
        return result
    except FileNotFoundError:
        return _result("failed", error="FileNotFoundError")
    except Exception as exc:
        return _result("failed", error=type(exc).__name__)

from __future__ import annotations

from pathlib import Path
from typing import Any

VALUE_SCORE = {
    'ai_metadata': 0,
    'positive_feedback': 1,
    'nearby_ai_context': 2,
    'xiaofanqie_obfuscated': 2,
    'xiaofanqie_compressed': 2,
    'possible_obfuscation': 2,
    'candidate': 3,
    'no_ai_metadata': 4,
}


def archive_size_bytes(root: str | Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def enforce_archive_budget(root: str | Path, image_records: list[dict[str, Any]], *, max_bytes: int, enabled: bool = True) -> list[Path]:
    if not enabled:
        return []
    root = Path(root)
    removed: list[Path] = []
    current = archive_size_bytes(root)
    if current <= max_bytes:
        return removed
    candidates = []
    for record in image_records:
        kept_path = record.get('kept_path')
        if not kept_path:
            continue
        path = Path(kept_path)
        if not path.exists() or not path.is_file():
            continue
        reason = str(record.get('retention_reason') or '')
        value = VALUE_SCORE.get(reason, 5)
        # Lower id is older; lower value is more valuable, so delete high value-score / older first.
        candidates.append((value, int(record.get('id') or 0), path))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    for _, _, path in candidates:
        if current <= max_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            current -= size
            removed.append(path)
        except FileNotFoundError:
            continue
    return removed

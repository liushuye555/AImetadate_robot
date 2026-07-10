from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(slots=True)
class CandidateImage:
    scope: str
    sha256: str
    path: Path
    created_at: float
    score: int = 0


def find_recent_candidate(candidates: list[CandidateImage], *, scope: str, now: float, window_seconds: int) -> CandidateImage | None:
    eligible = [c for c in candidates if c.scope == scope and now - c.created_at <= window_seconds]
    if not eligible:
        return None
    return max(eligible, key=lambda c: c.created_at)


def promote_candidate(candidate: CandidateImage, archive_root: str | Path) -> Path:
    archive_root = Path(archive_root)
    suffix = candidate.path.suffix or '.img'
    dest = archive_root / candidate.sha256[:2] / f'{candidate.sha256}{suffix}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.move(str(candidate.path), str(dest))
    else:
        candidate.path.unlink(missing_ok=True)
    candidate.path = dest
    return dest


def cleanup_candidates(candidates: list[CandidateImage], *, now: float, ttl_seconds: int) -> list[CandidateImage]:
    kept = []
    for candidate in candidates:
        if now - candidate.created_at > ttl_seconds:
            candidate.path.unlink(missing_ok=True)
        else:
            kept.append(candidate)
    return kept

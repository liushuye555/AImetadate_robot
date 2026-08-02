from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .build_image_view import build_view
from .resource_view import write_resource_pages
from .store import Store


def deduplicate_image_storage(project_dir: str | Path, store: Store) -> int:
    project_dir = Path(project_dir)
    archive_root = project_dir / 'data' / 'images' / 'ai'
    candidate_root = project_dir / 'data' / 'images' / 'candidates'
    archive = {path.stem: path for path in archive_root.rglob('*') if path.is_file()}
    candidates = {path.stem: path for path in candidate_root.rglob('*') if path.is_file()}
    removed = 0
    for digest, candidate in candidates.items():
        target = archive.get(digest)
        if target is None:
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
    for digest, path in {**candidates, **archive}.items():
        target = archive.get(digest) or path
        store.set_image_path_for_sha(digest, target)
    return removed


def prune_empty_dirs(root: str | Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    removed = 0
    dirs = sorted([p for p in root.rglob('*') if p.is_dir()], key=lambda p: len(p.parts), reverse=True)
    for path in dirs:
        try:
            path.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def cleanup_expired_candidates(project_dir: str | Path, *, ttl_hours: int = 24) -> int:
    """删除超过 TTL 未晋升的候选图片（文件 + DB 记录），并清空候选目录孤儿文件。"""
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    candidate_root = project_dir / 'data' / 'images' / 'candidates'
    if not db.exists():
        return 0
    cutoff = datetime.now().astimezone() - timedelta(hours=max(1, ttl_hours))
    removed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, kept_path, seen_at FROM images WHERE retention_reason='candidate'"
        ).fetchall()
        for row_id, kept_path, seen_at in rows:
            try:
                seen = datetime.fromisoformat(str(seen_at or '').replace('Z', '+00:00'))
                seen = seen.astimezone() if seen.tzinfo else seen.replace(tzinfo=cutoff.tzinfo)
            except Exception:
                seen = None
            if seen is not None and seen >= cutoff:
                continue
            if kept_path:
                try:
                    path = Path(kept_path)
                    if path.exists():
                        path.unlink()
                        removed += 1
                except OSError:
                    pass
            conn.execute("DELETE FROM images WHERE id=?", (row_id,))
        conn.commit()
    if candidate_root.exists():
        for p in candidate_root.rglob('*'):
            if p.is_file():
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        prune_empty_dirs(candidate_root)
    return removed


def remove_sticker_records(project_dir: str | Path) -> int:
    """删除已判定为表情包的图片记录与文件。"""
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    removed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, kept_path FROM images WHERE retention_reason='sticker_filtered'"
        ).fetchall()
        for row_id, kept_path in rows:
            if kept_path:
                try:
                    path = Path(kept_path)
                    if path.exists():
                        path.unlink()
                        removed += 1
                except OSError:
                    pass
            conn.execute("DELETE FROM images WHERE id=?", (row_id,))
        conn.commit()
    return removed


def reclassify_possible_obfuscation(project_dir: str | Path, *, threshold: int = 10, reencode_threshold: float = 6.5) -> int:
    """重分类图片。

    优先级：
    1. 小番茄混淆（Gilbert 曲线逆置换验证）→ xiaofanqie_obfuscated（算法级确认）；
    2. pHash 匹配 AI 归档 → possible_obfuscation（旧启发式，可能误判）；
    3. JPEG 块状伪影过高 → possible_reencode（弱信号）。
    """
    from .gilbert_obfuscation import analyze_image
    from .obfuscation import find_obfuscated_match, image_phash, jpeg_blockiness
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    with sqlite3.connect(db) as conn:
        # 1) 补建 AI 归档哈希索引
        known = {str(row[0]) for row in conn.execute('SELECT sha256 FROM image_hashes')}
        for sha, kept_path in conn.execute(
            "SELECT sha256, kept_path FROM images WHERE retention_reason='ai_metadata' AND kept_path IS NOT NULL"
        ).fetchall():
            if sha in known:
                continue
            path = Path(kept_path)
            if not path.exists():
                continue
            try:
                store.save_image_hash(sha, image_phash(path))
                known.add(sha)
            except Exception:
                continue
        # 2) 无元数据/候选/疑似图先做小番茄混淆算法级验证（带缓存）
        archive_hashes = store.archive_hashes()
        for row_id, kept_path, format, sha256 in conn.execute(
            "SELECT id, kept_path, format, sha256 FROM images "
            "WHERE retention_reason IN ('candidate', 'no_ai_metadata', 'possible_obfuscation', 'possible_reencode') "
            "AND kept_path IS NOT NULL"
        ).fetchall():
            path = Path(kept_path)
            if not path.exists():
                continue
            cached = store.obfuscation_score(str(sha256 or '')) if sha256 else None
            if cached is not None:
                xfq_result = {'obfuscated': cached[2], 'ratio': cached[0], 'layers': cached[1]}
            else:
                try:
                    xfq_result = analyze_image(path)
                except Exception:
                    xfq_result = None
                if xfq_result is not None:
                    try:
                        store.save_obfuscation_score(
                            str(sha256 or ''),
                            ratio=float(xfq_result['ratio']),
                            layers=xfq_result.get('layers'),
                            obfuscated=bool(xfq_result.get('obfuscated')),
                        )
                    except Exception:
                        pass
            if xfq_result and xfq_result.get('obfuscated'):
                conn.execute("UPDATE images SET retention_reason='xiaofanqie_obfuscated' WHERE id=?", (row_id,))
                changed += 1
                continue
            try:
                phash_value = image_phash(path)
            except Exception:
                continue
            if archive_hashes and find_obfuscated_match(phash_value, archive_hashes, threshold=threshold):
                conn.execute("UPDATE images SET retention_reason='possible_obfuscation' WHERE id=?", (row_id,))
                changed += 1
            elif str(format or '').upper().startswith('JPEG'):
                try:
                    if jpeg_blockiness(path) >= reencode_threshold:
                        conn.execute("UPDATE images SET retention_reason='possible_reencode' WHERE id=?", (row_id,))
                        changed += 1
                except Exception:
                    continue
        conn.commit()
    return changed


def sync_image_files(project_dir: str | Path, *, ttl_hours: int = 24) -> dict[str, int]:
    project_dir = Path(project_dir)
    store = Store(project_dir / 'data' / 'bot.db')
    image_duplicates_removed = deduplicate_image_storage(project_dir, store)
    missing_cleared = store.clear_missing_image_paths(project_dir)
    candidates_removed = cleanup_expired_candidates(project_dir, ttl_hours=ttl_hours)
    obfuscation_reclassified = reclassify_possible_obfuscation(project_dir)
    empty_candidate_dirs = prune_empty_dirs(project_dir / 'data' / 'images' / 'candidates')
    counts = build_view(project_dir)
    resource_counts = write_resource_pages(project_dir / 'data' / 'view', store)
    return {'image_duplicates_removed': image_duplicates_removed, 'missing_cleared': missing_cleared, 'candidates_removed': candidates_removed, 'obfuscation_reclassified': obfuscation_reclassified, 'empty_candidate_dirs': empty_candidate_dirs, **counts, **resource_counts}


def main() -> int:
    parser = argparse.ArgumentParser(description='Synchronize image DB paths with disk and rebuild view')
    parser.add_argument('--project-dir', default='.')
    args = parser.parse_args()
    result = sync_image_files(Path(args.project_dir).resolve())
    for key, value in sorted(result.items()):
        print(f'{key}: {value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

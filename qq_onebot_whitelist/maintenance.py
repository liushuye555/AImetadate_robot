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
    # 批量更新 kept_path：逐条开连接写库在归档量大时会慢 5~10 分钟
    updates = []
    for digest, path in {**candidates, **archive}.items():
        target = archive.get(digest) or path
        updates.append((str(target), digest))
    if updates:
        with sqlite3.connect(store.path) as conn:
            conn.executemany('UPDATE images SET kept_path = ? WHERE sha256 = ?', updates)
            conn.commit()
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
    """重分类图片：小番茄混淆（Gilbert 曲线逆置换验证）。

    - 算法级确认 → xiaofanqie_obfuscated（并自动还原）；
    - 重压/缩放弱信号 → xiaofanqie_compressed；
    - 其余图退回 no_ai_metadata（旧 pHash/块状伪影启发式分类已退役）。
    """
    from .gilbert_obfuscation import analyze_image
    from .gilbert_obfuscation import restore_image
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    with sqlite3.connect(db) as conn:
        # 无元数据/候选/疑似图做小番茄混淆算法级验证（带缓存）
        for row_id, kept_path, format, sha256, reason in conn.execute(
            "SELECT id, kept_path, format, sha256, retention_reason FROM images "
            "WHERE retention_reason IN ('candidate', 'no_ai_metadata', 'possible_obfuscation', 'possible_reencode') "
            "AND kept_path IS NOT NULL"
        ).fetchall():
            path = Path(kept_path)
            if not path.exists():
                continue
            cached = store.obfuscation_score(str(sha256 or '')) if sha256 else None
            if cached is not None and cached[3] is not None:
                xfq_result = {
                    'obfuscated': cached[2],
                    'ratio': cached[0],
                    'layers': cached[1],
                    'confidence': cached[3],
                }
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
                            confidence=xfq_result.get('confidence') or 'none',
                        )
                    except Exception:
                        pass
            if xfq_result and xfq_result.get('obfuscated'):
                if xfq_result.get('confidence') == 'confirmed':
                    reason = 'xiaofanqie_obfuscated'
                else:
                    reason = 'xiaofanqie_compressed'
                conn.execute("UPDATE images SET retention_reason=? WHERE id=?", (reason, row_id))
                # 确认档自动解混淆：还原原图并存到 images/restored/
                if reason == 'xiaofanqie_obfuscated' and xfq_result.get('layers'):
                    try:
                        restored_root = project_dir / 'data' / 'images' / 'restored'
                        restored, _ = restore_image(
                            path,
                            restored_root / f'{sha256}.png',
                            layers=xfq_result.get('layers'),
                        )
                        conn.execute("UPDATE images SET restored_path=? WHERE id=?", (str(restored), row_id))
                    except Exception:
                        pass
                changed += 1
                continue
            # 旧启发式临时分类退役：非混淆图退回普通无元数据
            if reason in ('possible_obfuscation', 'possible_reencode'):
                conn.execute("UPDATE images SET retention_reason='no_ai_metadata' WHERE id=?", (row_id,))
                changed += 1
        conn.commit()
    return changed


def restore_confirmed_obfuscation(project_dir: str | Path) -> int:
    """为已确认的小番茄混淆图补齐自动还原图（images/restored/ + DB restored_path）。"""
    from .gilbert_obfuscation import restore_image
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    restored_root = project_dir / 'data' / 'images' / 'restored'
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, sha256, kept_path FROM images "
            "WHERE retention_reason='xiaofanqie_obfuscated' AND restored_path IS NULL "
            "AND kept_path IS NOT NULL"
        ).fetchall()
        for row_id, sha256, kept_path in rows:
            path = Path(kept_path)
            if not path.exists():
                continue
            cached = store.obfuscation_score(str(sha256 or '')) if sha256 else None
            layers = cached[1] if cached else None
            try:
                restored, _ = restore_image(
                    path,
                    restored_root / f'{sha256}.png',
                    layers=layers,
                )
                conn.execute(
                    'UPDATE images SET restored_path=? WHERE id=?',
                    (str(restored), row_id),
                )
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
    obfuscation_restored = restore_confirmed_obfuscation(project_dir)
    empty_candidate_dirs = prune_empty_dirs(project_dir / 'data' / 'images' / 'candidates')
    counts = build_view(project_dir)
    resource_counts = write_resource_pages(project_dir / 'data' / 'view', store)
    return {'image_duplicates_removed': image_duplicates_removed, 'missing_cleared': missing_cleared, 'candidates_removed': candidates_removed, 'obfuscation_reclassified': obfuscation_reclassified, 'obfuscation_restored': obfuscation_restored, 'empty_candidate_dirs': empty_candidate_dirs, **counts, **resource_counts}


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

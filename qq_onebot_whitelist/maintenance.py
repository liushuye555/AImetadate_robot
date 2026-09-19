from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from .build_image_view import build_view
from .gilbert_obfuscation import analyze_image, safe_restore
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

    - 算法级确认且无上下文分类 → xiaofanqie_obfuscated（并自动还原）；
    - 算法级确认但命中 02/03 上下文分类 → 保留原分类并标记 deobfuscated（报告遮罩）；
    - 重压/缩放弱信号 → xiaofanqie_compressed；
    - 其余图退回 no_ai_metadata（旧 pHash/块状伪影启发式分类已退役）。
    """
    from .gilbert_obfuscation import analyze_image, safe_restore
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    decisions: list[tuple[int, str, str | None, str | None]] = []
    context_reasons = ('positive_feedback', 'prompt_bound', 'params_discussion')
    with sqlite3.connect(db) as conn:
        confirmed_shas = {
            str(r[0]) for r in conn.execute(
                "SELECT DISTINCT sha256 FROM images WHERE deobfuscated=1 AND sha256 IS NOT NULL"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT id, kept_path, format, sha256, retention_reason FROM images "
            "WHERE retention_reason IN ('candidate', 'no_ai_metadata', 'possible_obfuscation', 'possible_reencode') "
            "AND kept_path IS NOT NULL"
        ).fetchall()
    # 两阶段：先全部判定（独立连接，避免外层写事务内再开连接导致 SQLite 锁）
    archive_root = project_dir / 'data' / 'images' / 'ai'
    for row_id, kept_path, format, sha256, reason in rows:
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
        elif sha256 and str(sha256) in confirmed_shas:
            # 同 sha 已有确认标记（文件可能已是还原图，无法再分析）
            xfq_result = {'obfuscated': True, 'ratio': 0.5, 'layers': None, 'confidence': 'confirmed'}
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
            confirmed = xfq_result.get('confidence') == 'confirmed'
            context_reason = None
            if confirmed and reason in context_reasons:
                # 交叉分类：05 为主分类，上下文分类单独记录（02/03 遮罩显示）
                new_reason = 'xiaofanqie_obfuscated'
                context_reason = reason
            else:
                new_reason = 'xiaofanqie_obfuscated' if confirmed else 'xiaofanqie_compressed'
            restored_final = None
            # 确认档：还原即替换（删混淆原图、归档指向还原图）
            if confirmed and sha256:
                try:
                    current = analyze_image(path)
                    if current and current.get('obfuscated'):
                        tmp_dir = project_dir / 'data' / 'tmp'
                        tmp_dir.mkdir(parents=True, exist_ok=True)
                        final = safe_restore(
                            path,
                            tmp_dir / f'{sha256}.restore.png',
                            archive_root,
                            str(sha256),
                            layers=xfq_result.get('layers'),
                        )
                        restored_final = str(final) if final is not None else None
                    else:
                        # 文件已是还原内容：只标记，不重还原
                        restored_final = str(path)
                except Exception:
                    pass
            decisions.append((row_id, new_reason, restored_final, context_reason))
        elif reason in ('possible_obfuscation', 'possible_reencode'):
            # 旧启发式临时分类退役：非混淆图退回 04 候选（TTL 自动清理）
            decisions.append((row_id, 'candidate', None, None))
    if decisions:
        with sqlite3.connect(db) as conn:
            for row_id, new_reason, restored_final, context_reason in decisions:
                if restored_final:
                    conn.execute(
                        "UPDATE images SET retention_reason=?, kept_path=?, restored_path=?, deobfuscated=1, context_reason=? WHERE id=?",
                        (new_reason, restored_final, restored_final, context_reason, row_id),
                    )
                else:
                    conn.execute(
                        "UPDATE images SET retention_reason=?, context_reason=? WHERE id=?",
                        (new_reason, context_reason, row_id),
                    )
            conn.commit()
    return len(decisions)


def restore_confirmed_obfuscation(project_dir: str | Path) -> int:
    """为已确认的小番茄混淆图补齐自动还原并替换为唯一存档（删原图）。"""
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    archive_root = project_dir / 'data' / 'images' / 'ai'
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, sha256, kept_path FROM images "
            "WHERE retention_reason IN ('xiaofanqie_obfuscated', 'prompt_bound', 'params_discussion', 'positive_feedback') "
            "AND deobfuscated=0 "
            "AND kept_path IS NOT NULL"
        ).fetchall()
        for row_id, sha256, kept_path in rows:
            path = Path(kept_path)
            if not path.exists():
                continue
            cached = store.obfuscation_score(str(sha256 or '')) if sha256 else None
            if cached is not None and cached[3] is not None:
                # 已分析过（含负结果）：直接复用缓存，避免每轮同步全量重分析
                if cached[2] and cached[3] == 'confirmed':
                    layers = cached[1]
                else:
                    continue
            else:
                # 存量 02/03 图片可能从未写入 image_hashes；先现场检测，避免
                # 只有新采集图片才能自动解混淆。
                try:
                    detected = analyze_image(path)
                except Exception:
                    detected = None
                if not (detected and detected.get('obfuscated') and detected.get('confidence') == 'confirmed'):
                    # 负结果同样落缓存：本轮分析一次，后续同步直接跳过
                    if detected is not None and sha256:
                        try:
                            store.save_obfuscation_score(
                                str(sha256), ratio=float(detected.get('ratio') or 0.0),
                                layers=detected.get('layers'), obfuscated=False,
                                confidence=detected.get('confidence') or 'none',
                            )
                        except Exception:
                            pass
                    continue
                layers = detected.get('layers')
                if sha256:
                    try:
                        store.save_obfuscation_score(
                            str(sha256), ratio=float(detected['ratio']),
                            layers=layers, obfuscated=True, confidence='confirmed',
                        )
                    except Exception:
                        pass
            try:
                tmp_dir = project_dir / 'data' / 'tmp'
                tmp_dir.mkdir(parents=True, exist_ok=True)
                final = safe_restore(
                    path,
                    tmp_dir / f'{sha256}.restore.png',
                    archive_root,
                    str(sha256 or ''),
                    layers=layers,
                )
                if final is not None:
                    store.mark_image_deobfuscated(
                        row_id,
                        kept_path=str(final),
                        restored_path=str(final),
                    )
                    changed += 1
            except Exception:
                continue
        conn.commit()
    return changed


def reclassify_historical_03(project_dir: str | Path) -> int:
    """存量 03 重分类：按绑定规则重判 prompt_bound / params_discussion / candidate。"""
    from .prompt_binding import bind_prompt_for_image
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    decisions: list[tuple[str, str | None, int]] = []
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, scope, raw_json FROM images WHERE retention_reason='nearby_ai_context'"
        ).fetchall()
    # 两阶段：先全部判定（独立连接读库，避免外层写事务内再开连接导致 SQLite 锁）
    for row_id, scope, raw_json in rows:
        try:
            message_db_id = int(json.loads(raw_json or '{}').get('message_db_id'))
        except Exception:
            message_db_id = None
        records = store.recent_records_before(str(scope), message_db_id, limit=6) if scope else []
        kind, prompt = bind_prompt_for_image(records)
        if kind == 'prompt':
            decisions.append(('prompt_bound', prompt[:2000], row_id))
        elif kind == 'params':
            decisions.append(('params_discussion', None, row_id))
        else:
            decisions.append(('candidate', None, row_id))
    if decisions:
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "UPDATE images SET retention_reason=?, bound_prompt=? WHERE id=?",
                [(kind, prompt, row_id) for kind, prompt, row_id in decisions],
            )
            conn.commit()
    return len(decisions)


def backfill_prompt_keys(project_dir: str | Path) -> int:
    """为存量 01 图按 text_excerpt 回填 prompt_key（sha1 前 16 位）。"""
    import hashlib
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, text_excerpt FROM images "
            "WHERE retention_reason='ai_metadata' AND prompt_key IS NULL AND text_excerpt IS NOT NULL"
        ).fetchall()
        for row_id, excerpt in rows:
            text = str(excerpt or '')
            if not text.strip():
                continue
            pk = hashlib.sha1(text.encode('utf-8', errors='replace')).hexdigest()[:16]
            conn.execute('UPDATE images SET prompt_key=? WHERE id=?', (pk, row_id))
            changed += 1
        conn.commit()
    return changed


def rekey_prompt_signatures(project_dir: str | Path) -> int:
    """为存量 ComfyUI 01 图按"完整工作流"重算 prompt_key（修复仅文本节点分组的过度聚合）。"""
    from .image_meta import extract_prompt_signature
    from .build_image_view import source_path

    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, kept_path FROM images "
            "WHERE retention_reason='ai_metadata' AND ai_source='ComfyUI'"
        ).fetchall()
        for row_id, kept_path in rows:
            if not kept_path:
                continue
            src = source_path(project_dir, kept_path)
            if not src.exists():
                continue
            pk = extract_prompt_signature(src)
            if not pk:
                continue
            cur = conn.execute('SELECT prompt_key FROM images WHERE id=?', (row_id,)).fetchone()
            if cur and cur[0] == pk:
                continue
            conn.execute('UPDATE images SET prompt_key=? WHERE id=?', (pk, row_id))
            changed += 1
            if changed % 200 == 0:
                conn.commit()  # 分批提交，避免长时间锁库阻塞采集
        conn.commit()
    return changed


def reclassify_prompt_judge(project_dir: str | Path, *, mode: str = 'rule') -> int:
    """对存量 prompt_bound 行做 LLM 复核（mode=llm/both 时）；不通过的降级。"""
    if mode == 'rule':
        return 0
    from .prompt_judge import llm_judge_prompt, prompt_hash
    from .prompt_binding import is_params_message
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, scope, raw_json, bound_prompt FROM images "
            "WHERE retention_reason='prompt_bound' AND bound_prompt IS NOT NULL"
        ).fetchall()
        for row_id, scope, raw_json, bound in rows:
            prompt = str(bound or '')
            if not prompt.strip():
                continue
            phash = prompt_hash(prompt)
            cached = store.get_prompt_judge(phash)
            if cached is None:
                keep, _ = llm_judge_prompt(prompt)
                store.set_prompt_judge(phash, keep)
            else:
                keep = cached
            if keep:
                continue
            # 复核不通过：按参数讨论降级或转候选
            records = []
            if scope:
                try:
                    message_db_id = int(json.loads(raw_json or '{}').get('message_db_id'))
                except Exception:
                    message_db_id = None
                records = store.recent_records_before(str(scope), message_db_id, limit=6)
            if any(is_params_message(str(r.get('text') or '')) for r in records[-6:]):
                conn.execute("UPDATE images SET retention_reason='params_discussion', bound_prompt=NULL WHERE id=?", (row_id,))
            else:
                conn.execute("UPDATE images SET retention_reason='candidate', bound_prompt=NULL WHERE id=?", (row_id,))
            changed += 1
        conn.commit()
    return changed


def reclassify_params_judge(project_dir: str | Path, *, mode: str = 'rule') -> int:
    """存量参数讨论 LLM 复核（mode=llm/both）：只问没答/闲聊 → 降级候选。"""
    if mode == 'rule':
        return 0
    from .ai_discussion_judge import judge_params_batch
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, bound_prompt FROM images "
            "WHERE retention_reason='params_discussion' AND bound_prompt IS NOT NULL"
        ).fetchall()
    texts = [str(r[1] or '') for r in rows]
    verdicts = judge_params_batch(texts, store=store)
    downgrade_ids = [row_id for row_id, verdict in zip((r[0] for r in rows), verdicts) if not verdict]
    with sqlite3.connect(db) as conn:
        for row_id in downgrade_ids:
            conn.execute("UPDATE images SET retention_reason='candidate', bound_prompt=NULL WHERE id=?", (row_id,))
            changed += 1
        conn.commit()
    return changed


def cleanup_stale_tmp_files(project_dir: str | Path, *, max_age_hours: float = 24) -> int:
    """清掉下载中断/处理异常留下的孤儿临时文件（.download-* 等）。

    只认修改时间超过 max_age_hours 的文件——正在处理中的临时件不会被误删。
    """
    tmp_dir = Path(project_dir) / 'data' / 'tmp'
    if not tmp_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in tmp_dir.iterdir():
        try:
            if not entry.is_file() or entry.name.startswith('.git'):
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            entry.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def sync_image_files(project_dir: str | Path, *, ttl_hours: int = 24) -> dict[str, int]:
    project_dir = Path(project_dir)
    store = Store(project_dir / 'data' / 'bot.db')
    from .config import load_config
    config = load_config(project_dir / 'config.yaml')
    archive_budget_removed = 0
    try:
        from .archive_budget import enforce_archive_budget
        removed = enforce_archive_budget(
            project_dir / 'data' / 'images' / 'ai',
            store.image_records_with_paths(),
            max_bytes=max(1, int(config.max_archive_mb)) * 1024 * 1024,
        )
        archive_budget_removed = len(removed)
        if removed:
            print(f'archive budget: removed {len(removed)} files')
    except Exception as exc:
        print(f'archive budget failed: {type(exc).__name__}: {exc}')
    stale_tmp_removed = cleanup_stale_tmp_files(project_dir)
    if stale_tmp_removed:
        print(f'stale tmp cleanup: removed {stale_tmp_removed} files')
    image_duplicates_removed = deduplicate_image_storage(project_dir, store)
    missing_cleared = store.clear_missing_image_paths(project_dir)
    candidates_removed = cleanup_expired_candidates(project_dir, ttl_hours=ttl_hours)
    obfuscation_reclassified = reclassify_possible_obfuscation(project_dir)
    obfuscation_restored = restore_confirmed_obfuscation(project_dir)
    historical_03 = reclassify_historical_03(project_dir)
    prompt_keys_backfilled = backfill_prompt_keys(project_dir)
    prompt_judge_reclassified = reclassify_prompt_judge(project_dir, mode=config.prompt_judge_mode)
    params_judge_reclassified = reclassify_params_judge(project_dir, mode=config.ai_discussion_judge)
    empty_candidate_dirs = prune_empty_dirs(project_dir / 'data' / 'images' / 'candidates')
    # DeepSeek 视觉复核 02/03 类错分图（默认关；限批 + 只在错峰窗口跑，省 token）
    vision_stats = {'vision_checked': 0, 'vision_demoted': 0}
    try:
        from .vision_recheck import recheck_batch
        vision_stats = recheck_batch(project_dir, config)
    except Exception as exc:
        print(f'vision recheck failed: {type(exc).__name__}: {exc}')
    counts = build_view(project_dir)
    resource_counts = write_resource_pages(project_dir / 'data' / 'view', store)
    counts.update(vision_stats)
    return {'archive_budget_removed': archive_budget_removed, 'stale_tmp_removed': stale_tmp_removed, 'image_duplicates_removed': image_duplicates_removed, 'missing_cleared': missing_cleared, 'candidates_removed': candidates_removed, 'obfuscation_reclassified': obfuscation_reclassified, 'obfuscation_restored': obfuscation_restored, 'historical_03_reclassified': historical_03, 'prompt_keys_backfilled': prompt_keys_backfilled, 'prompt_judge_reclassified': prompt_judge_reclassified, 'params_judge_reclassified': params_judge_reclassified, 'empty_candidate_dirs': empty_candidate_dirs, **counts, **resource_counts}


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

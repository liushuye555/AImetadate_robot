"""历史记录来源重判（一次性维护，纯本地解析，不花 AI token）。

旧规则（6649929 之前）把通用参数词 steps/scale 当 NovelAI 证据且 NovelAI 优先于
A1111，导致大量 WebUI 图被误标 NovelAI（实测 2876 条里真 NovelAI 仅 31 条）。
本脚本对 kept_path 非空的记录重新解析原图元数据：

- 优先用新版 classify_ai_source 全文重判（强证据确认、弱证据 suspect:）；
- 无文本证据时按 PNG chunk 键名裁决：Software/Source/Comment → NovelAI，
  parameters → A1111（WebUI 专有键）；
- PNG 顺带扫 alpha 隐写（verified 提升为 NovelAI）；
- 同一 sha 只解析一次，结果复用到所有引用该内容的记录。

用法：python -m qq_onebot_whitelist.reclass_historical
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sqlite3

from .image_meta import SUSPECT_PREFIX, parse_image_metadata


def _verdict_from_meta(meta, meta_keys: list[str]) -> tuple[int, str]:
    """把解析结果折叠成 (has_ai_metadata, ai_source)；文本弱证据时用键名兜底。"""
    if meta.stego_state == 'verified':
        return 1, 'NovelAI'
    if meta.has_ai_metadata and meta.ai_source and not meta.ai_source.startswith(SUSPECT_PREFIX):
        return 1, meta.ai_source
    # 文本只有弱证据或没有证据：键名是更硬的结构证据
    keys = {k.lower() for k in meta_keys}
    if keys & {'software', 'source', 'description'} and 'title' in keys:
        return 1, 'NovelAI'  # NovelAI 导出的 tEXt 结构键
    if 'parameters' in keys:
        return 1, 'A1111'  # WebUI 的 parameters chunk
    if meta.has_ai_metadata and meta.ai_source:
        return 1, meta.ai_source  # 保留 suspect: 疑似
    return 0, ''


def reclass_historical(db_path: str | Path) -> dict[str, int]:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, sha256, kept_path FROM images "
            "WHERE kept_path IS NOT NULL AND merged_into IS NULL AND retention_reason = 'ai_metadata'"
        ).fetchall()
        verdicts: dict[str, tuple[int, str]] = {}  # sha -> verdict
        stats: Counter = Counter()
        for row in rows:
            sha = str(row['sha256'] or '')
            if sha in verdicts:
                stats['sha_cache_hits'] += 1
                continue
            path = Path(str(row['kept_path']))
            if not path.exists():
                stats['missing_files'] += 1
                continue
            try:
                meta = parse_image_metadata(path)
            except Exception:
                stats['parse_errors'] += 1
                continue
            verdicts[sha] = _verdict_from_meta(meta, meta.metadata_keys)
            stats['parsed'] += 1
            if meta.stego_state == 'verified':
                stats['stego_verified'] += 1
            elif meta.stego_state == 'suspected':
                stats['stego_suspected'] += 1
        changed: Counter = Counter()
        for row in rows:
            sha = str(row['sha256'] or '')
            verdict = verdicts.get(sha)
            if verdict is None:
                continue
            has_ai, source = verdict
            old = conn.execute(
                'SELECT has_ai_metadata, COALESCE(ai_source, \'\') FROM images WHERE id = ?',
                (row['id'],),
            ).fetchone()
            if old is None:
                continue
            old_has, old_src = int(old[0] or 0), old[1]
            if old_has == has_ai and old_src == source:
                continue
            conn.execute(
                'UPDATE images SET has_ai_metadata = ?, ai_source = ? WHERE id = ?',
                (has_ai, source, row['id']),
            )
            if old_src != source:
                changed[f'{old_src or "(none)"} -> {source or "(none)"}'] += 1
        conn.commit()
        result = {'records': len(rows), 'unique_contents': len(verdicts), **stats}
        result.update({f'changed: {k}': v for k, v in changed.most_common(15)})
        return result
    finally:
        conn.close()


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else 'data/bot.db'
    for key, value in reclass_historical(db).items():
        print(f'{key}: {value}')

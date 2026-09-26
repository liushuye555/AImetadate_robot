"""把带元数据的归档图按来源硬链接成稳定的导入目录（画风选择器等外部工具用）。

视图目录（data/view）是派生缓存，重分类会整体换位置，不适合当导入源；
归档本身（data/images/ai）按内容哈希命名、从不挪位，才是稳定位置。
本命令把当前判定的带元数据图按来源硬链接到 data/style-picker-import/<来源>/：
- NTFS 硬链接不占额外空间；
- 重分类/重建视图不影响这些路径；
- 重复执行即可刷新：新增图补上、失效链接与多余文件清掉。

用法：
    python -m qq_onebot_whitelist.export_style_links                 # 默认输出目录
    python -m qq_onebot_whitelist.export_style_links --out D:/导入图
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

DEFAULT_OUT = 'data/style-picker-import'


def _source_folder(ai_source: str | None) -> str:
    source = (ai_source or '').strip()
    if not source:
        return 'unknown'
    return source.replace(':', '-') or 'unknown'


def collect_links(db_path: Path) -> dict[Path, Path]:
    """返回 {目标硬链接路径: 归档源文件}；同一文件多行记录按文件去重。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT kept_path, ai_source FROM images "
            "WHERE has_ai_metadata=1 AND kept_path IS NOT NULL AND merged_into IS NULL "
            "ORDER BY CASE WHEN retention_reason='ai_metadata' THEN 0 ELSE 1 END, id"
        ).fetchall()
    finally:
        conn.close()
    plan: dict[Path, Path] = {}
    seen: set[Path] = set()
    for row in rows:
        src = Path(row['kept_path'])
        if not src.exists() or src in seen:
            continue  # 同一文件被多行记录引用（重发/上下文交叉）只导一次
        seen.add(src)
        dest = Path(_source_folder(row['ai_source'])) / src.name
        plan[dest] = src
    return plan


def build_links(db_path: Path, out_dir: Path) -> dict[str, int]:
    plan = collect_links(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {'linked': 0, 'kept': 0, 'copied': 0, 'stale_removed': 0}
    planned: set[Path] = set()
    for dest_rel, src in plan.items():
        dest = out_dir / dest_rel
        planned.add(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            try:
                if dest.samefile(src):
                    stats['kept'] += 1
                    continue
            except OSError:
                pass
            dest.unlink()
        try:
            os.link(src, dest)
            stats['linked'] += 1
        except OSError:
            shutil.copy2(src, dest)  # 跨卷等场景退回复制
            stats['copied'] += 1
    # 清掉本次计划之外的历史链接（重分类后来源变化/文件被还原替换等）
    for old in out_dir.rglob('*'):
        if old.is_file() and old.relative_to(out_dir) not in {p.relative_to(out_dir) for p in planned}:
            old.unlink()
            stats['stale_removed'] += 1
    for sub in list(out_dir.iterdir()):
        if sub.is_dir() and not any(sub.iterdir()):
            sub.rmdir()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', default=DEFAULT_OUT, help=f'输出目录（默认 {DEFAULT_OUT}）')
    parser.add_argument('--db', default='data/bot.db')
    args = parser.parse_args()
    stats = build_links(Path(args.db), Path(args.out))
    print(f'输出目录: {Path(args.out).resolve()}')
    for key, value in sorted(stats.items()):
        print(f'{key}: {value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

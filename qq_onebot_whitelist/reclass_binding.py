"""存量 02/03 绑定重判（一次性维护，纯规则，不花 AI token）。

历史数据挖掘（2026-09，全消息流 28.8 万条）发现旧规则两类系统性误判：
- 提示词绑定 582 行中 44% 的"提示词"其实是提到 lora/comfyui 的闲聊
  （旧 STRONG_PROMPT_RE 把裸工具词当提示词证据）；
- 参数讨论 721 行中 50% 的绑定文本只含"模型/生成/画质"类泛化词，
  另有 26 行连参数词都没有。

本脚本用新规则重判存量行，只降级不删除图片与记录：
- prompt_bound 且 bound_prompt 不再像提示词：
    像参数讨论 → params_discussion（保留 bound_prompt 作为讨论上下文）；
    否则 → nearby_ai_context（04 上下文分类，预算清理不删，图与记录保留）。
- params_discussion 且 bound_prompt 不再像参数讨论 → nearby_ai_context。

用法：
    python -m qq_onebot_whitelist.reclass_binding data/bot.db            # dry-run
    python -m qq_onebot_whitelist.reclass_binding data/bot.db --execute  # 写库
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sqlite3

from .prompt_binding import is_params_message, is_prompt_message

SAMPLE_LIMIT = 10


def reclass_binding(db_path: str | Path, *, dry_run: bool = True) -> dict[str, object]:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, retention_reason, bound_prompt FROM images "
            "WHERE retention_reason IN ('prompt_bound', 'params_discussion') "
            "AND bound_prompt IS NOT NULL AND TRIM(bound_prompt) != ''"
        ).fetchall()
        stats: Counter = Counter()
        changed: Counter = Counter()
        samples: list[str] = []
        decisions: list[tuple[str, str | None, int]] = []
        for row in rows:
            row_id = row['id']
            reason = row['retention_reason']
            bound = str(row['bound_prompt'] or '')
            if reason == 'prompt_bound':
                if is_prompt_message(bound):
                    stats['prompt_kept'] += 1
                    continue
                if is_params_message(bound):
                    decisions.append(('params_discussion', bound, row_id))
                    stats['prompt_demoted_to_params'] += 1
                else:
                    decisions.append(('nearby_ai_context', None, row_id))
                    stats['prompt_demoted_to_context'] += 1
            else:  # params_discussion
                if is_params_message(bound):
                    stats['params_kept'] += 1
                    continue
                decisions.append(('nearby_ai_context', None, row_id))
                stats['params_demoted_to_context'] += 1
        for new_reason, new_prompt, row_id in decisions:
            old = conn.execute(
                'SELECT retention_reason FROM images WHERE id = ?', (row_id,)
            ).fetchone()
            if old is None:
                continue
            transition = f'{old[0]} -> {new_reason}'
            changed[transition] += 1
            if len(samples) < SAMPLE_LIMIT:
                samples.append(f'id={row_id} {transition}')
            if dry_run:
                continue
            conn.execute(
                'UPDATE images SET retention_reason = ?, bound_prompt = ? WHERE id = ?',
                (new_reason, new_prompt, row_id),
            )
        if not dry_run:
            conn.commit()
        result = {'rows_scanned': len(rows), 'planned_changes': len(decisions),
                  'dry_run': 1 if dry_run else 0, **stats}
        result.update({f'changed: {k}': v for k, v in changed.most_common(10)})
        if samples:
            result['samples'] = ' | '.join(samples)
        return result
    finally:
        conn.close()


if __name__ == '__main__':
    import sys
    args = [a for a in sys.argv[1:] if a != '--execute']
    execute = '--execute' in sys.argv
    db = args[0] if args else 'data/bot.db'
    for key, value in reclass_binding(db, dry_run=not execute).items():
        print(f'{key}: {value}')

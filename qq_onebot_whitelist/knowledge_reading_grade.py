"""Conservative reading priorities, independent of truth and resolution status.

These derived labels never rewrite extraction values or source material. A
source-grounded tutorial can be useful without being a verified success report.
"""
from __future__ import annotations

from .knowledge_quality import normalize_quality


GRADES = {'a': '精选知识', 'b': '经验参考', 'c': '待核线索',
          'd': '一般讨论', 'unrated': '未评级'}
GRADE_ORDER = {name: index for index, name in enumerate(GRADES)}


def _grade(identifier, reason):
    return {'id': identifier, 'label': GRADES[identifier], 'reason': reason}


def grade_for(row, records):
    """Grade an item using its own group-local sources, never text length."""
    quality = row.get('quality')
    if not isinstance(quality, dict):
        return _grade('unrated', '缺少质量标注，暂不判断资料价值。')
    ids = row.get('evidence_ids', [])
    ids = ids if isinstance(ids, list) else []
    scope = row.get('scope')
    sources = [record for record in records if isinstance(record, dict)
               and type(record.get('id')) is int and record['id'] in ids
               and not record.get('context_only')
               and (not record.get('scope') or record.get('scope') == scope)]
    if not sources:
        return _grade('unrated', '原消息依据不可用，暂不判断资料价值。')
    normalized = normalize_quality(row, sources)
    if normalized is None:
        return _grade('d', '以推广内容为主，保留记录供回查，不进入优先阅读。')
    normalized_quality = normalized.get('quality') or {}
    basis = normalized_quality.get('basis')
    if normalized.get('value') == 'high' and row.get('evidence_state') in ('reported', 'verified'):
        return _grade('a', '具体条件、操作和结果引文通过原消息核对，满足现有精选标准；仍须留意适用范围与验证状态。')
    if basis in ('firsthand_result', 'reproducible_method'):
        if normalized_quality.get('result_quote'):
            return _grade('b', '有原消息支持的操作结果或方法引文，可作经验参考；尚未满足精选标准，不代表已验证或普遍有效。')
        return _grade('d', '尚无可核对的结果或方法引文，暂不作为经验推荐。')
    if basis in ('resource_lead', 'request'):
        return _grade('c', '保留资源或问题的原消息线索，尚缺实际效果或解决结果，按需查看。')
    return _grade('d', '以个人观点、临时状态或依据不足的讨论为主，可复用信息有限，默认收起。')


def thread_grade(events, rows_by_key, records_for):
    """Keep useful history, without inheriting an old A into a disputed result."""
    candidates = []
    merged = []
    for event in events:
        linked = rows_by_key.get(event.get('item_key'), {})
        row = {**linked, **event}
        # Event history stores immutable state but its quality is on the item.
        if not isinstance(event.get('quality'), dict) and isinstance(linked.get('quality'), dict):
            row['quality'] = linked['quality']
        merged.append(row)
        candidates.append(grade_for(row, records_for(row)))
    if not candidates:
        return _grade('unrated', '缺少可评级的讨论记录。')
    best = dict(min(candidates, key=lambda value: GRADE_ORDER[value['id']]))
    if best['id'] == 'd' and any(value['id'] == 'unrated' for value in candidates):
        return _grade('unrated', '部分讨论记录缺少质量或原消息依据，暂不将整个话题判为一般讨论。')
    latest = merged[-1]
    if best['id'] == 'a' and (latest.get('status') == 'disputed'
                              or latest.get('evidence_state') in ('unresolved', 'disputed')
                              or latest.get('category') in ('question', 'transient')):
        return _grade('b', '历史记录中有较完整方法，但后续仍未解决、存在分歧或属于时效信息，降为参考，不继承历史精选。')
    return best

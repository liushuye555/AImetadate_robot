"""Conservative quality metadata validation for extracted knowledge items."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .content_utils import redact_secrets


BASES = frozenset({
    'reproducible_method', 'firsthand_result', 'resource_lead', 'announcement',
    'service_status', 'personal_opinion', 'promotion', 'request', 'unsupported',
})

QUALITY_SYSTEM = '''
每个 knowledge item 必须增加 quality 对象：
{"basis":"reproducible_method|firsthand_result|resource_lead|announcement|service_status|personal_opinion|promotion|request|unsupported","conditions":[具体适用条件],"actions":[原文支持的具体操作],"result_quote":{"message_id":当前材料中的整数消息编号,"quote":"该消息原文中的连续精确结果句"}或null}。
严格区分可复用方法、本人操作结果、未经实测的资源线索、公告、服务状态、个人观点、推广和请求。resource_lead 即使没有实测也可作为候选线索；announcement 和 service_status 必须归为 transient 且 candidate；request 归为 question 且 candidate；promotion 不输出为知识条目。
不得仅凭工具自我介绍、夸赞、价格或泛化建议评为 high。可复用教程即使尚无群友亲测也可有价值，但必须有具体且非空的 conditions 与 actions，逐字引用原文里的条件/步骤短句，并附上与结论直接相关、逐字来自当前证据消息或文件摘录的 result_quote；没有这些证据一律 candidate。firsthand_result还须有真实操作结果，不把计划或建议当成实测。价值等级不能替代验证状态，未经实测仍为reported。引用不可改写、拼接或引用材料之外的内容。没有 quality 时系统会按 candidate 处理。
'''.strip()

def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the separate quality annotation table within the caller's transaction."""
    conn.execute('''CREATE TABLE IF NOT EXISTS item_quality (
        item_key TEXT PRIMARY KEY,
        quality_json TEXT NOT NULL,
        quality_reason TEXT NOT NULL
    )''')


def save_quality(conn: sqlite3.Connection, item_key: str, item: dict[str, Any]) -> None:
    quality = item.get('quality')
    conn.execute(
        'INSERT OR REPLACE INTO item_quality(item_key, quality_json, quality_reason) VALUES (?, ?, ?)',
        (item_key, json.dumps(quality, ensure_ascii=False), str(item.get('quality_reason') or 'missing_annotation')),
    )


def decorate_quality(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    """Attach the stored annotation and its grading reason to an item mapping."""
    result = dict(item)
    try:
        row = conn.execute('SELECT quality_json, quality_reason FROM item_quality WHERE item_key=?',
                           (item.get('key'),)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table: item_quality' not in str(exc):
            raise
        return result
    if row:
        result['quality'] = json.loads(row['quality_json'] if isinstance(row, sqlite3.Row) else row[0])
        result['quality_reason'] = row['quality_reason'] if isinstance(row, sqlite3.Row) else row[1]
    return result


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for entry in value[:20]:
        if isinstance(entry, str) and entry.strip():
            result.append(redact_secrets(entry.strip())[:500])
    return result


def _validated_quote(value: Any, item: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    mid, quote = value.get('message_id'), value.get('quote')
    if type(mid) is not int or not isinstance(quote, str) or not quote.strip():
        return None
    quote = quote.strip()
    if mid not in item.get('evidence_ids', []):
        return None
    for record in records:
        if record.get('id') == mid and not record.get('context_only'):
            sources = [record.get('text')]
            files = record.get('files')
            if isinstance(files, list):
                sources.extend((f.get('preview') or {}).get('text') for f in files
                               if isinstance(f, dict) and isinstance(f.get('preview'), dict))
            if any(isinstance(source, str) and quote in source for source in sources):
                return {'message_id': mid, 'quote': redact_secrets(quote)[:1000]}
    return None


def _supported_details(values: list[str], item: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    if not values or not item.get('evidence_ids'):
        return False
    allowed = set(item['evidence_ids'])
    sources: list[str] = []
    for record in records:
        if record.get('id') not in allowed or record.get('context_only'):
            continue
        if isinstance(record.get('text'), str):
            sources.append(record['text'])
        for file in record.get('files', []):
            if isinstance(file, dict) and isinstance(file.get('preview'), dict):
                preview = file['preview'].get('text')
                if isinstance(preview, str):
                    sources.append(preview)
    return all(any(value in source for source in sources) for value in values)


def normalize_quality(item: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a copied, conservatively graded item; return ``None`` for promotion.

    ``quality`` remains on the result and in the separate quality annotation table.
    Missing or malformed annotations never grant high value.
    """
    result = dict(item)
    raw = item.get('quality')
    if not isinstance(raw, dict):
        result['quality'] = None
        result['value'] = 'candidate'
        result['quality_reason'] = 'missing_or_invalid_quality'
        return result

    basis = raw.get('basis')
    if basis not in BASES:
        basis = 'unsupported'
    conditions = _strings(raw.get('conditions'))
    actions = _strings(raw.get('actions'))
    quote = _validated_quote(raw.get('result_quote'), item, records)
    result['quality'] = {
        'basis': basis,
        'conditions': conditions,
        'actions': actions,
        'result_quote': quote,
    }

    if basis == 'promotion':
        return None
    result['value'] = 'candidate'
    if basis in ('announcement', 'service_status'):
        result['category'] = 'transient'
    elif basis == 'request':
        result['category'] = 'question'
    elif basis == 'personal_opinion':
        result['category'] = 'knowledge'
        if not str(result.get('title') or '').startswith('群友说法：'):
            result['title'] = '群友说法：' + str(result.get('title') or '')

    if (item.get('value') == 'high' and item.get('evidence_state') not in ('unresolved', 'disputed')
            and result.get('category') not in ('question', 'transient')
            and basis in ('reproducible_method', 'firsthand_result')
            and _supported_details(conditions, item, records)
            and _supported_details(actions, item, records) and quote is not None):
        result['value'] = 'high'
        result['quality_reason'] = 'specific_details_and_exact_source_quote'
    else:
        result['quality_reason'] = 'insufficient_source_grounding_for_high'
    return result


def validate_quality(item: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compatibility alias for callers that name the normalization step validation."""
    return normalize_quality(item, records)

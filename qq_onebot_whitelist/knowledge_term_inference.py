"""Optional, unconfirmed context-based terminology annotations.

These annotations are deliberately stored apart from ``terms``: examples of
usage can suggest a meaning, but they never count as confirmed definitions.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .content_utils import redact_secrets


SCHEMA = '''
CREATE TABLE IF NOT EXISTS term_annotations (
    term_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    note TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    aliases_json TEXT NOT NULL
)
'''


def _clean(value: Any, limit: int = 1000) -> str:
    if not isinstance(value, str):
        return ''
    return redact_secrets(value.strip())[:limit]


def _normalized(text: str) -> str:
    return ''.join(text.casefold().split())


def _unique_strings(values: Any, *, limit: int, size: int = 300) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean(value, size)
        key = _normalized(item)
        if item and key not in seen:
            result.append(item)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def prepare_inference(row: dict, records: list[dict], *, enabled: bool = False) -> dict:
    """Return a cleaned term; validate opt-in usage examples against this batch.

    ``definition_evidence``/``supporting_contexts`` are preserved untouched as
    established by the caller. Inference is descriptive metadata only.
    """
    result = dict(row)
    result.update(inference_kind='unconfirmed', inference_note='', inference_evidence=[],
                  alternatives=[], aliases=[])
    if not enabled or not isinstance(row, dict):
        return result

    term = _clean(row.get('term'), 500)
    evidence_ids = set(row.get('evidence_ids', [])) if isinstance(row.get('evidence_ids'), list) else set()
    sources = {r.get('id'): r for r in records if isinstance(r, dict) and type(r.get('id')) is int}
    aliases = _unique_strings(row.get('aliases', []), limit=8, size=100)
    # A model-supplied alias is usable only when it occurs in a cited source.
    aliases = [a for a in aliases if any(a.casefold() in str(sources.get(mid, {}).get('text') or '').casefold()
                                         for mid in evidence_ids if mid in sources)]
    names = [n for n in [term, *aliases] if n]
    raw_evidence = row.get('inference_evidence', row.get('context_evidence', []))
    valid: list[dict] = []
    seen_ids: set[int] = set()
    seen_text: set[str] = set()
    current_seen = False
    if isinstance(raw_evidence, list):
        for item in raw_evidence[:20]:
            if not isinstance(item, dict):
                continue
            mid = item.get('message_id', item.get('id'))
            quote = item.get('quote')
            source = sources.get(mid) if type(mid) is int and mid in evidence_ids else None
            if source is None or not isinstance(quote, str) or not quote.strip():
                continue
            quote = quote.strip()
            original = str(source.get('text') or '')
            if quote not in original or not any(n.casefold() in quote.casefold() for n in names):
                continue
            normalized = _normalized(original)
            if mid in seen_ids or normalized in seen_text:
                continue
            valid.append({'message_id': mid, 'quote': _clean(quote, 1000)})
            seen_ids.add(mid)
            seen_text.add(normalized)
            current_seen = current_seen or not source.get('context_only', False)
    alternatives = _unique_strings(row.get('alternatives', []), limit=5, size=300)
    requested_kind = row.get('inference_kind')
    sufficient = len(valid) >= 2 and current_seen
    kind = requested_kind if requested_kind in ('inferred', 'ambiguous') else 'unconfirmed'
    if not sufficient:
        valid, kind = [], 'unconfirmed'
    elif kind == 'ambiguous' and len(alternatives) < 2:
        kind = 'unconfirmed'
    elif kind == 'inferred' and not _clean(row.get('inference_note')):
        kind = 'unconfirmed'
    result.update(inference_kind=kind,
                  inference_note=_clean(row.get('inference_note')) if kind in ('inferred', 'ambiguous') else '',
                  inference_evidence=valid,
                  alternatives=alternatives if kind in ('inferred', 'ambiguous') else [],
                  aliases=aliases)
    return result


def save_annotation(conn: sqlite3.Connection, tkey: str, meta: dict) -> None:
    """Persist validated annotation metadata unless the keyed term is manual."""
    conn.execute(SCHEMA)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'terms' in tables:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(terms)')}
        if {'key', 'origin'} <= columns and conn.execute(
                "SELECT 1 FROM terms WHERE key=? AND origin='user' LIMIT 1", (tkey,)).fetchone():
            return
    existing = conn.execute('SELECT kind,evidence_json FROM term_annotations WHERE term_key=?', (tkey,)).fetchone()
    meta = meta if isinstance(meta, dict) else {}
    kind = meta.get('inference_kind')
    if kind not in ('explicit', 'inferred', 'ambiguous', 'unconfirmed'):
        kind = 'unconfirmed'
    note = _clean(meta.get('inference_note')) if kind in ('inferred', 'ambiguous') else ''
    evidence = []
    for item in meta.get('inference_evidence', []) if isinstance(meta.get('inference_evidence'), list) else []:
        if (isinstance(item, dict) and type(item.get('message_id')) is int
                and isinstance(item.get('quote'), str) and item['quote'].strip()):
            evidence.append({'message_id': item['message_id'], 'quote': _clean(item['quote'])})
    alternatives = _unique_strings(meta.get('alternatives', []), limit=5) if kind in ('inferred', 'ambiguous') else []
    aliases = _unique_strings(meta.get('aliases', []), limit=8, size=100)
    # Disabled inference produces an empty unconfirmed payload. Keep the last
    # useful explanation so toggling the feature off stops learning without
    # erasing reviewable evidence already collected.
    if (existing is not None and kind == 'unconfirmed' and not note and not evidence
            and existing[0] in ('inferred', 'ambiguous') and existing[1] not in ('', '[]')):
        return
    conn.execute('''INSERT OR REPLACE INTO term_annotations
        (term_key,kind,note,evidence_json,alternatives_json,aliases_json) VALUES (?,?,?,?,?,?)''',
        (tkey, kind, note, json.dumps(evidence, ensure_ascii=False),
         json.dumps(alternatives, ensure_ascii=False), json.dumps(aliases, ensure_ascii=False)))


def decorate_term(conn: sqlite3.Connection, term: dict) -> dict:
    """Add saved annotation fields for rendering, keeping user terms manual."""
    result = dict(term)
    if result.get('origin') == 'user':
        result.update(inference_kind='explicit', inference_note='', inference_evidence=[],
                      alternatives=[], aliases=[])
        return result
    key = result.get('key')
    if not isinstance(key, str):
        return result
    try:
        row = conn.execute('SELECT * FROM term_annotations WHERE term_key=?', (key,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is None:
        return result
    def load(field: str, fallback: Any) -> Any:
        try:
            return json.loads(row[field])
        except (ValueError, TypeError, IndexError):
            return fallback
    result.update(inference_kind=row['kind'], inference_note=row['note'],
                  inference_evidence=load('evidence_json', []),
                  alternatives=load('alternatives_json', []), aliases=load('aliases_json', []))
    return result

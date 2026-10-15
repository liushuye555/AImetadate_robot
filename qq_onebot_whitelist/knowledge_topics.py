"""Group-local topic history, written inside the caller's knowledge transaction.

Topic association is an AI proposal, not a keyword join. Callers must show only
``thread_candidates`` to the model and pass that same list as ``allowed_threads``.
The prompt should keep different people's incidents separate, require a specific
link_reason, and treat conflicting feedback conservatively. Events retain that
reason and source speakers so associations remain auditable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3

from .content_utils import redact_secrets


SCHEMA = '''
CREATE TABLE IF NOT EXISTS knowledge_threads (
 scope TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
 status TEXT NOT NULL, known TEXT NOT NULL, missing TEXT NOT NULL,
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 source_time TEXT, source_stamp REAL, source_message_id INTEGER NOT NULL,
 category TEXT NOT NULL DEFAULT 'knowledge', resource_json TEXT NOT NULL DEFAULT '{}',
 value TEXT NOT NULL DEFAULT 'candidate',
 PRIMARY KEY(scope,id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_threads_scope
 ON knowledge_threads(scope,source_stamp,source_message_id);
CREATE TABLE IF NOT EXISTS knowledge_thread_events (
 scope TEXT NOT NULL, id TEXT NOT NULL, thread_id TEXT NOT NULL,
 item_key TEXT NOT NULL, run_key TEXT NOT NULL, created_at TEXT NOT NULL,
 source_time TEXT, source_stamp REAL, source_message_id INTEGER NOT NULL,
 status TEXT NOT NULL, requested_status TEXT NOT NULL, status_reason TEXT NOT NULL,
 title TEXT NOT NULL, summary TEXT NOT NULL, known TEXT, missing TEXT,
 link_reason TEXT NOT NULL, evidence_state TEXT NOT NULL,
 evidence_json TEXT NOT NULL, resolution_json TEXT NOT NULL, sources_json TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'knowledge', resource_json TEXT NOT NULL DEFAULT '{}',
 value TEXT NOT NULL DEFAULT 'candidate',
 PRIMARY KEY(scope,id),
 FOREIGN KEY(scope,thread_id) REFERENCES knowledge_threads(scope,id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_thread_events_thread
 ON knowledge_thread_events(scope,thread_id,source_stamp,source_message_id);
'''

STATUSES = frozenset(('open', 'in_progress', 'resolved', 'disputed'))
CATEGORIES = frozenset(('knowledge', 'question', 'resource', 'transient'))


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create auxiliary tables without committing an enclosing transaction."""
    for statement in SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    for table in ('knowledge_threads', 'knowledge_thread_events'):
        columns = {row[1] for row in conn.execute('PRAGMA table_info(' + table + ')')}
        for column, default in (('category', "'knowledge'"), ('resource_json', "'{}'"),
                                ('value', "'candidate'")):
            if column not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}')


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value: object) -> str:
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value: object, limit: int = 5000) -> str:
    if isinstance(value, list):
        value = '\n'.join(v for v in value[:20] if isinstance(v, str))
    return redact_secrets(value.strip())[:limit] if isinstance(value, str) else ''


def _limit(value: object, maximum: int) -> int:
    if type(value) is not int:
        raise ValueError('话题条数必须为整数')
    return min(max(value, 0), maximum)


def _category(item: dict) -> str:
    category = item.get('category')
    if category is not None:
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError('话题分类格式不正确')
        return category
    if item.get('evidence_state') == 'unresolved' or item.get('kind') in ('未解决', '未解决问题', 'question'):
        return 'question'
    return 'resource' if item.get('kind') in ('资源', 'resource') else 'knowledge'


def _resource(item: dict, category: str) -> dict:
    """Persist the already-validated resource details without retaining extra model keys."""
    resource = item.get('resource')
    if category != 'resource' or not isinstance(resource, dict):
        return {}
    result = {key: _text(resource[key], 2000 if key == 'url' else 1200)
              for key in ('url', 'name', 'purpose', 'feedback') if isinstance(resource.get(key), str)}
    result['status'] = 'unverified'
    return result


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _source_position(records: list[dict]) -> tuple[str | None, float | None, int]:
    positions = []
    for record in records:
        try:
            when = datetime.fromisoformat(record.get('time') or '')
            if when.tzinfo is None:
                continue
            stamp = when.timestamp()
            positions.append((stamp, record['id'], when.astimezone(timezone.utc).isoformat()))
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    if positions:
        stamp, mid, source_time = max(positions)
        return source_time, stamp, mid
    return None, None, max((record['id'] for record in records), default=0)


def _newer(stamp: float | None, mid: int, old: dict) -> bool:
    # Unknown original time must never replace a state supported by a known time.
    old_stamp = old['source_stamp']
    if stamp is None or old_stamp is None:
        if stamp is not None:
            return True
        if old_stamp is not None:
            return False
        return mid > old['source_message_id']
    return (stamp, mid) > (old_stamp, old['source_message_id'])


def _resolution(item: dict, sources: dict[int, dict], evidence: list[int]) -> list[dict]:
    proposed = item.get('resolution_evidence', [])
    if not isinstance(proposed, list) or len(proposed) > 60:
        return []
    verified = {}
    for row in proposed:
        if not isinstance(row, dict):
            continue
        mid, quote = row.get('message_id'), row.get('quote')
        record = sources.get(mid) if type(mid) is int and mid in evidence else None
        if record is None or not isinstance(quote, str) or not quote.strip():
            continue
        quote = quote.strip()
        if quote in record.get('text', ''):
            clean = _text(quote)
            verified[(mid, clean)] = {'message_id': mid, 'quote': clean}
    return [verified[key] for key in sorted(verified)]


def record_updates(conn: sqlite3.Connection, scope: str, items: list[dict], records: list[dict], *,
                   allowed_threads: list[dict], now: str, run_key: str) -> list[dict]:
    """Append immutable events and advance current state by original message time.

    ``records`` are the actual model input, including optional context_only rows.
    Existing associations require both a same-scope database row and an id in the
    supplied candidate snapshot. Invalid associations raise ValueError and roll
    back this entire call. Unsupported resolutions become open/in_progress and
    candidate; unsupported verified claims become reported. Events retain the
    original requested_status (including caller-normalized proposals) and reason.

    Returns {thread_id, event_id, status, inserted} per item. No commit is issued;
    the caller owns these writes, including when this starts a transaction. One
    item_key contributes one event per topic, even if a retry changes its prose
    or run_key. New feedback should have its own evidence-based item_key.
    """
    if not isinstance(scope, str) or not scope or not isinstance(now, str) or not now:
        raise ValueError('话题必须指定群与写入时间')
    if not isinstance(items, list) or len(items) > 60:
        raise ValueError('话题更新列表格式不正确')
    if not isinstance(records, list) or any(r.get('scope') != scope for r in records):
        raise ValueError('话题证据不能跨群')
    sources = {r['id']: r for r in records if type(r.get('id')) is int and r['id'] > 0}
    available_ids = set(sources) | {r['quoted_id'] for r in records if type(r.get('quoted_id')) is int}
    current_ids = {mid for mid, row in sources.items() if not row.get('context_only')}
    allowed = {row.get('id') for row in allowed_threads
               if isinstance(row, dict) and row.get('scope') == scope and isinstance(row.get('id'), str)}
    results = []
    if not conn.in_transaction:
        # A SAVEPOINT alone commits when released. Start a caller-owned write
        # transaction instead, also serializing standalone concurrent writers.
        conn.execute('BEGIN IMMEDIATE')
    conn.execute('SAVEPOINT knowledge_topic_updates')
    try:
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('title'), str) or not item['title'].strip():
                raise ValueError('话题更新缺少标题')
            evidence = item.get('evidence_ids')
            if (not isinstance(evidence, list) or not evidence
                    or not all(type(mid) is int and mid > 0 and mid in available_ids for mid in evidence)
                    or not current_ids.intersection(evidence)):
                raise ValueError('话题更新缺少本群本批次原消息证据')
            evidence = sorted(set(evidence))
            title = _text(item['title'])
            # Match KnowledgeDB's pre-existing identity when no explicit key is supplied.
            identity = json.dumps([scope, item['title'], evidence], ensure_ascii=False)
            item_key = item.get('item_key') or sha256(identity.encode('utf-8')).hexdigest()
            if not isinstance(item_key, str) or len(item_key) > 256:
                raise ValueError('话题知识编号格式不正确')
            thread_id = item.get('thread_id')
            link_reason = _text(item.get('link_reason'), 1200)
            if thread_id is not None and thread_id != '':
                if not isinstance(thread_id, str) or thread_id not in allowed:
                    raise ValueError('话题关联不在本群本次允许的旧话题中')
                if not link_reason:
                    raise ValueError('关联旧话题必须说明具体关联理由')
            else:
                thread_id = 'topic_' + _digest([scope, item_key])
            old_rows = _rows(conn.execute('SELECT * FROM knowledge_threads WHERE scope=? AND id=?',
                                         (scope, thread_id)))
            old = old_rows[0] if old_rows else None
            if item.get('thread_id') and old is None:
                raise ValueError('话题关联不存在于本群')
            state = item.get('evidence_state', 'reported')
            category = _category(item)
            resource = _resource(item, category)
            value = item.get('value', 'candidate')
            if value not in ('high', 'candidate'):
                raise ValueError('话题价值等级格式不正确')
            requested = (item.get('requested_status') or item.get('status')
                         or ('disputed' if state == 'disputed' else 'open'))
            if requested not in STATUSES:
                raise ValueError('话题状态格式不正确')
            resolution = _resolution(item, sources, evidence)
            status, status_reason = requested, ''
            if requested == 'resolved' and (state != 'verified' or not resolution
                    or not current_ids.intersection(row['message_id'] for row in resolution)):
                status = 'open' if state == 'unresolved' else 'disputed' if state == 'disputed' else 'in_progress'
                status_reason = 'resolved_requires_verified_current_source_quote'
                value = 'candidate'
                if state == 'verified':
                    state = 'reported'
            position_ids = ({row['message_id'] for row in resolution} & current_ids
                            if status == 'resolved' else set(evidence) & current_ids)
            source_time, stamp, mid = _source_position([sources[i] for i in position_ids])
            known = _text(item['known']) if 'known' in item else None
            missing = _text(item['missing']) if 'missing' in item else None
            source_details = [{'message_id': i, 'time': sources[i].get('time'),
                               'actor_key': sources[i].get('actor_key'),
                               'context_only': bool(sources[i].get('context_only'))}
                              for i in evidence if i in sources]
            event = dict(item_key=item_key, title=title, summary=_text(item.get('summary')),
                         status=status, requested_status=requested, status_reason=status_reason,
                         known=known, missing=missing, link_reason=link_reason,
                         evidence_state=state, evidence_ids=evidence,
                         resolution_evidence=resolution, sources=source_details,
                         category=category, resource=resource, value=value)
            event_id = 'event_' + _digest([scope, thread_id, item_key])
            previous = conn.execute('SELECT status FROM knowledge_thread_events WHERE scope=? AND id=?',
                                    (scope, event_id)).fetchone()
            if previous is not None:
                results.append(dict(thread_id=thread_id, event_id=event_id,
                                    status=previous[0], inserted=False))
                continue
            if old is None:
                conn.execute('INSERT INTO knowledge_threads '
                             '(scope,id,title,status,known,missing,evidence_json,created_at,updated_at,'
                             'source_time,source_stamp,source_message_id,category,resource_json,value) '
                             'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (scope, thread_id, title, status, known or '', missing or '', _json(evidence),
                              now, now, source_time, stamp, mid, category, _json(resource), value))
            inserted = conn.execute(
                'INSERT OR IGNORE INTO knowledge_thread_events '
                '(scope,id,thread_id,item_key,run_key,created_at,source_time,source_stamp,source_message_id,'
                'status,requested_status,status_reason,title,summary,known,missing,link_reason,evidence_state,'
                'evidence_json,resolution_json,sources_json,category,resource_json,value) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (scope, event_id, thread_id, item_key, str(run_key)[:512], now, source_time, stamp, mid,
                 status, requested, status_reason, title, event['summary'], known, missing, link_reason,
                 state, _json(evidence), _json(resolution), _json(source_details), category,
                 _json(resource), value)).rowcount == 1
            if old and inserted:
                union = sorted(set(json.loads(old['evidence_json'])) | set(evidence))
                conn.execute('UPDATE knowledge_threads SET evidence_json=? WHERE scope=? AND id=?',
                             (_json(union), scope, thread_id))
                if _newer(stamp, mid, old):
                    conn.execute('UPDATE knowledge_threads SET status=?,known=?,missing=?,updated_at=?, '
                                 'source_time=?,source_stamp=?,source_message_id=?,category=?,resource_json=?,value=? '
                                 'WHERE scope=? AND id=?',
                                 (status, old['known'] if known is None else known,
                                  old['missing'] if missing is None else missing, now, source_time, stamp, mid,
                                  category, _json(resource), value, scope, thread_id))
            results.append(dict(thread_id=thread_id, event_id=event_id, status=status, inserted=inserted))
        conn.execute('RELEASE SAVEPOINT knowledge_topic_updates')
    except BaseException:
        conn.execute('ROLLBACK TO SAVEPOINT knowledge_topic_updates')
        conn.execute('RELEASE SAVEPOINT knowledge_topic_updates')
        raise
    return results


def thread_candidates(conn: sqlite3.Connection, scope: str, limit: int = 12) -> list[dict]:
    """Return bounded group-local hints; none of these states imply verified facts."""
    rows = _rows(conn.execute(
        'SELECT id,scope,title,status,known,missing,evidence_json,category,value FROM knowledge_threads '
        'WHERE scope=? ORDER BY source_stamp DESC,source_message_id DESC,id LIMIT ?',
        (scope, _limit(limit, 50))))
    for row in rows:
        row['title'] = row['title'][:300]
        row['known'] = row['known'][:1600]
        row['missing'] = row['missing'][:1600]
        row['evidence_ids'] = json.loads(row.pop('evidence_json'))[-30:]
    return rows


def threads(conn: sqlite3.Connection, scope: str | None = None, limit: int = 200) -> list[dict]:
    """Read selected topics with their complete immutable event history."""
    query = 'SELECT * FROM knowledge_threads'
    args = []
    if scope is not None:
        query += ' WHERE scope=?'
        args.append(scope)
    rows = _rows(conn.execute(query + ' ORDER BY source_stamp DESC,source_message_id DESC,id LIMIT ?',
                              [*args, _limit(limit, 200)]))
    for row in rows:
        row['evidence_ids'] = json.loads(row.pop('evidence_json'))
        row['resource'] = json.loads(row.pop('resource_json'))
        events = _rows(conn.execute(
            'SELECT * FROM knowledge_thread_events WHERE scope=? AND thread_id=? '
            'ORDER BY source_stamp,source_message_id,id', (row['scope'], row['id'])))
        for event in events:
            for raw, field in (('evidence_json', 'evidence_ids'), ('resolution_json', 'resolution_evidence'),
                               ('sources_json', 'sources'), ('resource_json', 'resource')):
                event[field] = json.loads(event.pop(raw))
        row['events'] = events
    return rows

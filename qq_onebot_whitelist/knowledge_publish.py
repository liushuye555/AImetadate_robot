"""Explicitly publish reviewed offline history into the normal knowledge library.

This transfers derived records only. Original messages must already match the
live archive; runtime cursors, credentials, settings and file paths stay local.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import uuid

from .knowledge_config import group_scope
from .knowledge_store import KnowledgeDB, LOCAL_TZ


SCOPED_TABLES = ('runs', 'items', 'terms', 'knowledge_threads',
                 'knowledge_thread_events', 'knowledge_archives')
CHILD_TABLES = {'item_details': ('items', 'item_key'),
                'item_quality': ('items', 'item_key'),
                'item_organization': ('items', 'item_key'),
                'term_annotations': ('terms', 'term_key')}


def _readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)


def _evidence_ids(value, *, flat_ids=False):
    """Collect message references from stored evidence and summary structures."""
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, (dict, list)):
                yield from _evidence_ids(entry)
            elif flat_ids:
                yield entry
    elif isinstance(value, dict):
        for key, entry in value.items():
            if key in ('message_id', 'quoted_id', 'source_message_id') and entry is not None:
                yield entry
            elif key == 'evidence_ids':
                if not isinstance(entry, list):
                    raise ValueError('整理结果的证据格式无效，未发布')
                yield from _evidence_ids(entry, flat_ids=True)
            elif isinstance(entry, (dict, list)):
                yield from _evidence_ids(entry)


def _read_bundle(source, target, scope):
    with closing(_readonly(source / 'knowledge.db')) as conn, closing(_readonly(source / 'bot.db')) as messages:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        messages.execute('ATTACH DATABASE ? AS live', ((target / 'bot.db').resolve().as_uri() + '?mode=ro',))
        messages.execute('BEGIN')
        ids = {row[0] for row in messages.execute('SELECT id FROM messages WHERE scope=?', (scope,))}
        if not ids:
            raise ValueError('分析快照中没有本群原消息')
        # IDs alone are insufficient: snapshots from a different database can
        # reuse them. Check the content and original platform message identity.
        fields = ('scope', 'user_id', 'text', 'raw_json', 'message_key', 'links_json')
        differences = ' OR '.join(f's.{field} IS NOT m.{field}' for field in fields)
        mismatch = messages.execute(
            'SELECT count(*) FROM main.messages s LEFT JOIN live.messages m ON m.id=s.id '
            'WHERE s.scope=? AND (m.id IS NULL OR ' + differences + ')', (scope,)).fetchone()[0]
        if mismatch:
            raise ValueError(f'{mismatch} 条原消息与正式资料库不一致，未发布')
        bundle = {}
        for table in SCOPED_TABLES:
            query = 'SELECT * FROM ' + table + ' WHERE scope=?'
            if table == 'runs':
                query += " AND status='completed' AND kind NOT LIKE 'model:%' AND kind NOT IN ('optimize','compare')"
            bundle[table] = [dict(row) for row in conn.execute(query, (scope,))]
        for table, (parent, key) in CHILD_TABLES.items():
            bundle[table] = [dict(row) for row in conn.execute(
                f'SELECT c.* FROM {table} c JOIN {parent} p ON p.key=c.{key} WHERE p.scope=?', (scope,))]
        for rows in bundle.values():
            for row in rows:
                refs = []
                if row.get('source_message_id') is not None:
                    refs.append(row['source_message_id'])
                for field in ('evidence_json', 'contexts_json', 'resolution_json', 'sources_json',
                              'result_json', 'quality_json', 'organization_json'):
                    if row.get(field):
                        refs.extend(_evidence_ids(json.loads(row[field]), flat_ids=field == 'evidence_json'))
                if any(type(mid) is not int or mid not in ids for mid in refs):
                    raise ValueError('整理结果含快照之外或其他群的证据，未发布')
        item_keys = {r['key'] for r in bundle['items']}
        run_keys = {r['key'] for r in bundle['runs']}
        topic_keys = {r['id'] for r in bundle['knowledge_threads']}
        for event in bundle['knowledge_thread_events']:
            if event['item_key'] not in item_keys or event['run_key'] not in run_keys or event['thread_id'] not in topic_keys:
                raise ValueError('话题关联记录不完整，未发布')
        if not any(bundle[table] for table in ('items', 'terms', 'runs')):
            raise ValueError('分析目录没有可发布的整理结果')
        return bundle, ids


def publish_history(source_dir: Path, data_dir: Path, scope: str) -> dict:
    """Merge one reviewed group, rejecting conflicts rather than overwriting edits.

    The caller explicitly chooses an analysis directory. No directory discovery
    or fallback to arbitrary experimental results is performed.
    """
    source, target = Path(source_dir).resolve(), Path(data_dir).resolve()
    scope = group_scope(scope)
    if source == target or not all(path.is_file() for path in
            (source / 'knowledge.db', source / 'bot.db', target / 'bot.db')):
        raise ValueError('需要独立的分析目录及现有正式原消息库')
    bundle, ids = _read_bundle(source, target, scope)
    digest = sha256(json.dumps([scope, bundle], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    database_path = target / 'knowledge.db'
    backup = None
    if database_path.exists():
        backup = Path('backups') / ('knowledge-before-publish-' + uuid.uuid4().hex + '.db')
        (target / backup).parent.mkdir(parents=True, exist_ok=True)
        with closing(_readonly(database_path)) as before, closing(sqlite3.connect(target / backup)) as saved:
            before.backup(saved)
    db = KnowledgeDB(database_path)
    inserted = {}
    with db.conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for table, rows in bundle.items():
            schema = conn.execute('PRAGMA table_info(' + table + ')').fetchall()
            columns = [row['name'] for row in schema]
            primary = [row['name'] for row in sorted(schema, key=lambda row: row['pk']) if row['pk']]
            inserted[table] = 0
            for row in rows:
                if set(row) != set(columns) or not primary:
                    raise ValueError('分析库结构与正式库不兼容，未发布')
                previous = conn.execute('SELECT * FROM ' + table + ' WHERE ' +
                    ' AND '.join(key + '=?' for key in primary), [row[key] for key in primary]).fetchone()
                if previous:
                    if dict(previous) != row:
                        raise ValueError(f'{table} 存在内容冲突，已保留正式库修改，未发布')
                    continue
                conn.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES (' +
                             ','.join('?' for _ in columns) + ')', [row[key] for key in columns])
                inserted[table] += 1
        conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_publications (
            digest TEXT PRIMARY KEY, scope TEXT NOT NULL, source_directory TEXT NOT NULL,
            published_at TEXT NOT NULL, message_count INTEGER NOT NULL,
            first_id INTEGER NOT NULL, last_id INTEGER NOT NULL, counts_json TEXT NOT NULL)''')
        conn.execute('INSERT OR IGNORE INTO knowledge_publications VALUES (?,?,?,?,?,?,?,?)',
                     (digest, scope, str(source), datetime.now(LOCAL_TZ).isoformat(), len(ids),
                      min(ids), max(ids), json.dumps({table: len(rows) for table, rows in bundle.items()})))
    return {'status': 'published' if any(inserted.values()) else 'unchanged',
            'scope': scope, 'message_count': len(ids), 'inserted': inserted,
            'backup': str(backup) if backup else None}

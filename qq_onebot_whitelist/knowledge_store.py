"""Read original messages without migrations; keep derived knowledge separately."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .resources import extract_file_segments
from .store import reply_to_message_id
from .knowledge_grounding import effective_term, independent_definitions


LOCAL_TZ = timezone(timedelta(hours=8))


def date_bounds(start: str, end: str | None = None) -> tuple[int, int]:
    first = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=LOCAL_TZ)
    last = datetime.strptime(end or start, '%Y-%m-%d').replace(tzinfo=LOCAL_TZ) + timedelta(days=1)
    if last <= first:
        raise ValueError('结束日期不能早于开始日期')
    return int(first.timestamp()), int(last.timestamp())


def read_records(db_path: Path, scope: str, *, after_id: int = 0, limit: int = 100,
                 bounds: tuple[int, int] | None = None, recent: bool = False,
                 before_id: int | None = None) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        query = 'SELECT id,scope,user_id,text,raw_json,seen_at,links_json FROM messages WHERE scope=? AND id>?'
        args: list = [scope, after_id]
        if before_id is not None:
            query += ' AND id<=?'
            args.append(before_id)
        if bounds:
            query += " AND json_valid(raw_json) AND CAST(json_extract(raw_json,'$.time') AS INTEGER)>=? AND CAST(json_extract(raw_json,'$.time') AS INTEGER)<?"
            args.extend(bounds)
        query += ' ORDER BY id ' + ('DESC' if recent else 'ASC') + ' LIMIT ?'
        args.append(limit)
        rows = conn.execute(query, args).fetchall()
        if recent:
            rows.reverse()
        records = []
        for row in rows:
            try:
                raw = json.loads(row['raw_json'] or '{}')
                if not isinstance(raw, dict):
                    raw = {}
            except (ValueError, TypeError):
                raw = {}
            try:
                stamp = int(raw.get('time') or 0)
                when = datetime.fromtimestamp(stamp, LOCAL_TZ).isoformat() if stamp > 0 else None
            except (ValueError, TypeError, OSError, OverflowError):
                when = None
            reply = reply_to_message_id(raw)
            quote = ''
            quote_id = None
            quoted_actor_key = None
            if reply:
                found = conn.execute('SELECT id,text,user_id FROM messages WHERE scope=? AND message_key=? LIMIT 1', (scope, reply)).fetchone()
                quote = found['text'] if found else ''
                quote_id = found['id'] if found else None
                if found and found['user_id'] is not None and str(found['user_id']):
                    quoted_actor_key = sha256((scope + '\0' + str(found['user_id'])).encode('utf-8')).hexdigest()[:12]
            try:
                links = json.loads(row['links_json'] or '[]')
            except (ValueError, TypeError):
                links = []
            files = [{**f, 'scope': scope, 'message_id': row['id']} for f in extract_file_segments(raw)]
            actor_key = None
            if row['user_id'] is not None and str(row['user_id']):
                actor_key = sha256((scope + '\0' + str(row['user_id'])).encode('utf-8')).hexdigest()[:12]
            records.append(dict(id=row['id'], scope=scope, text=row['text'] or '', time=when,
                                quoted_text=quote or '', quoted_id=quote_id, links=links, files=files,
                                actor_key=actor_key, quoted_actor_key=quoted_actor_key,
                                segments=[s.get('type') for s in raw.get('message', []) if isinstance(s, dict)]
                                if isinstance(raw.get('message'), list) else []))
        return records
    finally:
        conn.close()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
 key TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL,
 status TEXT NOT NULL, tokens INTEGER NOT NULL, created_at TEXT NOT NULL,
 start_id INTEGER, end_id INTEGER, result_json TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS items (
 key TEXT PRIMARY KEY, scope TEXT NOT NULL, created_at TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT, topic TEXT, value TEXT,
 evidence_json TEXT NOT NULL, files_json TEXT NOT NULL,
 evidence_state TEXT NOT NULL DEFAULT 'reported'
);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON items(scope,created_at);
CREATE TABLE IF NOT EXISTS terms (
 key TEXT PRIMARY KEY, scope TEXT NOT NULL, term TEXT NOT NULL, meaning TEXT NOT NULL,
 evidence_json TEXT NOT NULL, status TEXT NOT NULL, contexts_json TEXT NOT NULL DEFAULT '[]',
 origin TEXT NOT NULL DEFAULT 'ai'
);
CREATE TABLE IF NOT EXISTS cursors (
 scope TEXT NOT NULL, kind TEXT NOT NULL, last_id INTEGER NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(scope,kind)
);
CREATE TABLE IF NOT EXISTS assets (
 scope TEXT NOT NULL, file_id TEXT NOT NULL, message_id INTEGER, name TEXT,
 sha256 TEXT, path TEXT, size INTEGER, status TEXT NOT NULL, error TEXT,
 source_json TEXT NOT NULL DEFAULT '{}',
 last_attempt_at TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(scope,file_id)
);
'''


class KnowledgeDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as conn:
            conn.executescript(SCHEMA)
            for table, column, default in [('items','evidence_state',"'reported'"), ('terms', 'contexts_json', "'[]'"), ('terms','origin',"'ai'"), ('assets', 'source_json', "'{}'"), ('assets','last_attempt_at',"''")]:
                if column not in {r[1] for r in conn.execute('PRAGMA table_info(' + table + ')')}:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}')

    @contextmanager
    def conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def claim(self, key: str, scope: str, kind: str, reserve: int, budget: int, start: int, end: int) -> dict | None:
        now = datetime.now(LOCAL_TZ).isoformat()
        with self.conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT * FROM runs WHERE key=?', (key,)).fetchone()
            if old and old['status'] == 'completed':
                return json.loads(old['result_json'])
            if old and old['status'] == 'running':
                age = datetime.now(LOCAL_TZ) - datetime.fromisoformat(old['created_at'])
                if age < timedelta(minutes=10):
                    raise RuntimeError('同一分析任务正在运行')
                conn.execute("UPDATE runs SET status='failed',error='interrupted' WHERE key=?", (key,))
            used = conn.execute('SELECT coalesce(sum(tokens),0) FROM runs WHERE scope=? AND day=?', (scope, now[:10])).fetchone()[0]
            if used + reserve > budget:
                raise RuntimeError('本群今日 AI 用量预算不足，任务未启动')
            # Failed/interrupted attempts retain their reservation; retry gets a separate attempt key.
            if old:
                attempt = key + ':' + now
                conn.execute('UPDATE runs SET key=? WHERE key=?', (attempt, key))
            conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (key, scope, kind, now[:10], 'running', reserve, now, start, end, None, None))
        return None

    def fail(self, key: str, error: str):
        with self.conn() as conn:
            conn.execute("UPDATE runs SET status='failed',error=? WHERE key=?", (error[:160], key))

    def finish(self, key: str, scope: str, result: dict, tokens: int, *, extraction: bool, glossary: bool):
        now = datetime.now(LOCAL_TZ).isoformat()
        with self.conn() as conn:
            conn.execute("UPDATE runs SET status='completed',tokens=?,result_json=? WHERE key=?",
                         (tokens, json.dumps(result, ensure_ascii=False), key))
            if extraction:
                for item in result.get('items', []):
                    identity = json.dumps([scope, item['title'], sorted(item['evidence_ids'])], ensure_ascii=False)
                    ikey = sha256(identity.encode()).hexdigest()
                    conn.execute('INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                                 (ikey, scope, now, item['title'], item['summary'], item['kind'], item['topic'], item['value'],
                                  json.dumps(item['evidence_ids']), json.dumps(item.get('file_ids', [])),item.get('evidence_state','reported')))
            if glossary:
                for term in result.get('terms', []):
                    if conn.execute("SELECT 1 FROM terms WHERE scope=? AND term=? AND origin='user' AND status='active'",
                                    (scope, term['term'])).fetchone():
                        continue
                    tkey = sha256(json.dumps([scope, term['term'], term['meaning']], ensure_ascii=False).encode()).hexdigest()
                    old = conn.execute('SELECT evidence_json,contexts_json FROM terms WHERE key=?', (tkey,)).fetchone()
                    evidence = sorted(set(term['evidence_ids']) | set(json.loads(old[0]) if old else []))
                    contexts = sorted(set(term.get('supporting_contexts', [])) | set(json.loads(old[1]) if old else []))
                    conflict = conn.execute('SELECT 1 FROM terms WHERE scope=? AND term=? AND meaning!=?',
                                            (scope, term['term'], term['meaning'])).fetchone()
                    status = 'candidate' if conflict or not independent_definitions(contexts) else 'active'
                    if conflict:
                        conn.execute("UPDATE terms SET status='candidate' WHERE scope=? AND term=?", (scope, term['term']))
                    conn.execute('INSERT OR REPLACE INTO terms VALUES (?,?,?,?,?,?,?,?)',
                                 (tkey, scope, term['term'], term['meaning'], json.dumps(evidence), status, json.dumps(contexts), 'ai'))

    def items(self, scope: str | None = None, keyword: str = '', limit: int = 200) -> list[dict]:
        with self.conn() as conn:
            query = 'SELECT * FROM items WHERE 1=1'
            args: list = []
            if scope:
                query += ' AND scope=?'
                args.append(scope)
            if keyword:
                query += " AND (instr(lower(title),lower(?))>0 OR instr(lower(body),lower(?))>0)"
                args.extend([keyword, keyword])
            return [dict(r) for r in conn.execute(query + ' ORDER BY created_at DESC LIMIT ?', [*args, limit])]

    def terms(self, scope: str) -> list[dict]:
        with self.conn() as conn:
            return [effective_term(dict(r)) for r in conn.execute('SELECT * FROM terms WHERE scope=? ORDER BY term LIMIT 60', (scope,))]

    def set_term(self, scope: str, term: str, meaning: str):
        key = sha256(json.dumps([scope,term,meaning],ensure_ascii=False).encode()).hexdigest()
        with self.conn() as conn:
            conn.execute("UPDATE terms SET status='candidate' WHERE scope=? AND term=?", (scope,term))
            conn.execute('INSERT OR REPLACE INTO terms VALUES (?,?,?,?,?,?,?,?)',
                         (key,scope,term,meaning,'[]','active','[]','user'))

    def cursor(self, scope: str, kind: str) -> tuple[int, str | None]:
        with self.conn() as conn:
            row = conn.execute('SELECT last_id,updated_at FROM cursors WHERE scope=? AND kind=?', (scope, kind)).fetchone()
        return (row[0], row[1]) if row else (0, None)

    def advance(self, scope: str, kind: str, last_id: int):
        with self.conn() as conn:
            conn.execute('INSERT INTO cursors VALUES (?,?,?,?) ON CONFLICT(scope,kind) DO UPDATE SET last_id=max(last_id,excluded.last_id),updated_at=excluded.updated_at',
                         (scope, kind, last_id, datetime.now(LOCAL_TZ).isoformat()))

    def asset(self, source: dict, result: dict):
        with self.conn() as conn:
            compact = {k: source.get(k) for k in ('scope','file_id','message_id','file_name','file_size','busid')}
            conn.execute('INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (source['scope'], source['file_id'], source['message_id'], source['file_name'],
                          result.get('sha256'), result.get('path'), result.get('size'), result['status'], result.get('error'), json.dumps(compact),
                          datetime.now(LOCAL_TZ).isoformat()))

    def asset_saved(self, scope: str, file_id: str) -> bool:
        with self.conn() as conn:
            row = conn.execute("SELECT path,size,sha256 FROM assets WHERE scope=? AND file_id=? AND status='saved'", (scope, file_id)).fetchone()
        if not row or not row[0]:
            return False
        try:
            path = Path(row[0])
            if not path.is_file() or path.stat().st_size != row[1]:
                return False
            digest = sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            return digest.hexdigest() == row[2]
        except OSError:
            return False

    def pending_assets(self, scope: str, limit: int = 3) -> list[dict]:
        # Recovery checks persisted assets as well; missing/corrupt originals are not "saved".
        with self.conn() as conn:
            saved = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE scope=? AND status='saved'", (scope,))]
        for asset in saved:
            if not self.asset_saved(scope, asset['file_id']):
                with self.conn() as conn:
                    conn.execute("UPDATE assets SET status='failed',error='IntegrityFailure',last_attempt_at='' WHERE scope=? AND file_id=?",
                                 (scope, asset['file_id']))
        with self.conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM assets WHERE scope=? AND status NOT IN ('saved','review') ORDER BY last_attempt_at,file_id LIMIT ?", (scope, limit))]

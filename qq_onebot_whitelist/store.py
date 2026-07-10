from __future__ import annotations

from contextlib import closing
from pathlib import Path
import json
import sqlite3
from typing import Any

from .summary import extract_links


def raw_message_ids(raw: dict[str, Any]) -> set[str]:
    ids = set()
    for key in ['message_id', 'message_seq', 'real_id']:
        value = raw.get(key)
        if value is not None and value != '':
            ids.add(str(value))
    return ids


def canonical_message_key(raw: dict[str, Any]) -> str | None:
    for key in ['message_id', 'real_id', 'message_seq']:
        value = raw.get(key)
        if value is not None and value != '':
            return str(value)
    return None


def reply_to_message_id(raw: dict[str, Any]) -> str | None:
    for segment in raw.get('message') or []:
        if isinstance(segment, dict) and segment.get('type') == 'reply':
            value = (segment.get('data') or {}).get('id')
            if value is not None and value != '':
                return str(value)
    return None

SCHEMA = '''
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  user_id TEXT,
  text TEXT,
  links_json TEXT,
  raw_json TEXT,
  message_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_scope_id ON messages(scope, id);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id, id);

CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  user_id TEXT,
  url TEXT,
  message_text TEXT,
  quoted_text TEXT,
  kind TEXT
);
CREATE INDEX IF NOT EXISTS idx_links_scope_id ON links(scope, id);
CREATE INDEX IF NOT EXISTS idx_links_url ON links(url);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  user_id TEXT,
  file_name TEXT,
  file_size INTEGER,
  url TEXT,
  kind TEXT,
  raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_scope_id ON files(scope, id);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind, id);

CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  user_id TEXT,
  url TEXT,
  sha256 TEXT,
  size INTEGER,
  format TEXT,
  width INTEGER,
  height INTEGER,
  metadata_keys_json TEXT,
  has_ai_metadata INTEGER,
  ai_source TEXT,
  text_excerpt TEXT,
  kept_path TEXT,
  retention_reason TEXT,
  raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_scope_id ON images(scope, id);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
CREATE INDEX IF NOT EXISTS idx_images_ai ON images(has_ai_metadata, ai_source);
CREATE INDEX IF NOT EXISTS idx_images_reason ON images(retention_reason, id);

CREATE TABLE IF NOT EXISTS daily_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_date TEXT UNIQUE,
  sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
  content TEXT
);

CREATE TABLE IF NOT EXISTS history_cursors (
  group_id TEXT PRIMARY KEY,
  newest_seq TEXT,
  oldest_seq TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_context_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  scope TEXT,
  start_message_id INTEGER,
  end_message_id INTEGER,
  model TEXT,
  summary TEXT,
  raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_context_scope_id ON ai_context_batches(scope, id);
'''


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.commit()

    def _migrate(self, conn) -> None:
        existing = {row[1] for row in conn.execute('PRAGMA table_info(links)').fetchall()}
        for name, ddl in {
            'message_text': 'ALTER TABLE links ADD COLUMN message_text TEXT',
            'quoted_text': 'ALTER TABLE links ADD COLUMN quoted_text TEXT',
            'kind': 'ALTER TABLE links ADD COLUMN kind TEXT',
        }.items():
            if name not in existing:
                conn.execute(ddl)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_links_kind ON links(kind, id)')
        message_cols = {row[1] for row in conn.execute('PRAGMA table_info(messages)').fetchall()}
        if 'message_key' not in message_cols:
            conn.execute('ALTER TABLE messages ADD COLUMN message_key TEXT')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_scope_key ON messages(scope, message_key) WHERE message_key IS NOT NULL')

    def record_message(self, *, scope: str, user_id: str, text: str, raw: dict[str, Any]) -> list[str]:
        links = extract_links(text)
        message_key = canonical_message_key(raw)
        with closing(sqlite3.connect(self.path)) as conn:
            if message_key:
                existing = conn.execute('SELECT 1 FROM messages WHERE scope = ? AND message_key = ?', (scope, message_key)).fetchone()
                if existing:
                    return []
            conn.execute(
                'INSERT INTO messages (scope, user_id, text, links_json, raw_json, message_key) VALUES (?, ?, ?, ?, ?, ?)',
                (scope, str(user_id), text, json.dumps(links, ensure_ascii=False), json.dumps(raw, ensure_ascii=False), message_key),
            )
            for url in links:
                conn.execute(
                    'INSERT INTO links (scope, user_id, url, message_text, quoted_text, kind) VALUES (?, ?, ?, ?, ?, ?)',
                    (scope, str(user_id), url, text, '', 'link'),
                )
            conn.commit()
        return links

    def message_row_id(self, scope: str, raw: dict[str, Any]) -> int | None:
        message_key = canonical_message_key(raw)
        if not message_key:
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT id FROM messages WHERE scope = ? AND message_key = ?',
                (scope, message_key),
            ).fetchone()
        return int(row[0]) if row else None

    def record_link(self, *, scope: str, user_id: str, url: str, message_text: str = '', quoted_text: str = '', kind: str = 'link') -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO links (scope, user_id, url, message_text, quoted_text, kind) VALUES (?, ?, ?, ?, ?, ?)',
                (scope, str(user_id), url, message_text, quoted_text, kind),
            )
            conn.commit()

    def record_file(self, *, scope: str, user_id: str, file_name: str, file_size: int | None, url: str | None, kind: str, raw: dict[str, Any]) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO files (scope, user_id, file_name, file_size, url, kind, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (scope, str(user_id), file_name, file_size, url, kind, json.dumps(raw, ensure_ascii=False)),
            )
            conn.commit()

    def record_image(self, *, scope: str, user_id: str, result: dict[str, Any], raw: dict[str, Any]) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                '''INSERT INTO images (
                  scope, user_id, url, sha256, size, format, width, height, metadata_keys_json,
                  has_ai_metadata, ai_source, text_excerpt, kept_path, retention_reason, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    scope,
                    str(user_id),
                    result.get('url'),
                    result.get('sha256'),
                    result.get('size'),
                    result.get('format'),
                    result.get('width'),
                    result.get('height'),
                    json.dumps(result.get('metadata_keys') or [], ensure_ascii=False),
                    1 if result.get('has_ai_metadata') else 0,
                    result.get('ai_source'),
                    result.get('text_excerpt'),
                    result.get('kept_path'),
                    result.get('retention_reason'),
                    json.dumps(raw, ensure_ascii=False),
                ),
            )
            conn.commit()

    def group_name_map(self) -> dict[str, str]:
        names: dict[str, str] = {}
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT scope, raw_json FROM messages WHERE scope LIKE 'group:%' ORDER BY id DESC"
            ).fetchall()
        for scope, raw_json in rows:
            group_id = str(scope).split(':', 1)[1] if ':' in str(scope) else str(scope)
            if group_id in names:
                continue
            try:
                raw = json.loads(raw_json or '{}')
            except Exception:
                raw = {}
            name = str(raw.get('group_name') or '').strip()
            if name:
                names[group_id] = name
                names[str(scope)] = name
        return names

    def recent_records(self, scope: str, limit: int = 100) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT id, seen_at, user_id, text, links_json, raw_json FROM messages WHERE scope = ? ORDER BY id DESC LIMIT ?',
                (scope, int(limit)),
            ).fetchall()
            context_rows = conn.execute(
                'SELECT text, raw_json FROM messages WHERE scope = ? ORDER BY id DESC LIMIT ?',
                (scope, max(int(limit) * 5, 500)),
            ).fetchall()
        by_message_id: dict[str, str] = {}
        for text, raw_json in context_rows:
            try:
                raw = json.loads(raw_json or '{}')
            except Exception:
                raw = {}
            for mid in raw_message_ids(raw):
                by_message_id[mid] = text or ''
        records = []
        for msg_id, seen_at, user_id, text, links_json, raw_json in reversed(rows):
            try:
                links = json.loads(links_json or '[]')
            except Exception:
                links = []
            try:
                raw = json.loads(raw_json or '{}')
            except Exception:
                raw = {}
            reply_id = reply_to_message_id(raw)
            records.append({
                'id': msg_id,
                'seen_at': seen_at,
                'user_id': user_id,
                'nickname': (raw.get('sender') or {}).get('nickname') or '',
                'card': (raw.get('sender') or {}).get('card') or '',
                'text': text or '',
                'links': links,
                'reply_to_message_id': reply_id,
                'quoted_text': by_message_id.get(reply_id or '') if reply_id else None,
            })
        return records

    def recent_records_all(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT id, seen_at, scope, user_id, text, links_json, raw_json FROM messages ORDER BY id DESC LIMIT ?',
                (int(limit),),
            ).fetchall()
        records = []
        for msg_id, seen_at, scope, user_id, text, links_json, raw_json in reversed(rows):
            try:
                links = json.loads(links_json or '[]')
            except Exception:
                links = []
            try:
                raw = json.loads(raw_json or '{}')
            except Exception:
                raw = {}
            records.append({
                'id': msg_id,
                'seen_at': seen_at,
                'scope': scope,
                'user_id': user_id,
                'nickname': (raw.get('sender') or {}).get('nickname') or '',
                'card': (raw.get('sender') or {}).get('card') or '',
                'text': text or '',
                'links': links,
                'reply_to_message_id': reply_to_message_id(raw),
                'quoted_text': None,
            })
        return records

    def recent_text_context(self, scope: str, limit: int = 8) -> str:
        records = self.recent_records(scope, limit=limit)
        return '\n'.join(str(record.get('text') or '') for record in records if str(record.get('text') or '').strip())

    def recent_links(self, scope: str | None = None, limit: int = 20) -> list[str]:
        with closing(sqlite3.connect(self.path)) as conn:
            if scope:
                rows = conn.execute('SELECT url FROM links WHERE scope = ? ORDER BY id DESC LIMIT ?', (scope, int(limit))).fetchall()
            else:
                rows = conn.execute('SELECT url FROM links ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        return [row[0] for row in rows]

    def recent_link_records(self, limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            if since:
                rows = conn.execute(
                    'SELECT seen_at, scope, user_id, url, message_text, quoted_text, kind FROM links WHERE seen_at > ? ORDER BY id DESC LIMIT ?',
                    (since, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT seen_at, scope, user_id, url, message_text, quoted_text, kind FROM links ORDER BY id DESC LIMIT ?',
                    (int(limit),),
                ).fetchall()
        return [dict(seen_at=r[0], scope=r[1], user_id=r[2], url=r[3], message_text=r[4] or '', quoted_text=r[5] or '', kind=r[6] or 'link') for r in rows]

    def recent_files(self, limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            if since:
                rows = conn.execute(
                    'SELECT seen_at, scope, user_id, file_name, file_size, url, kind, raw_json FROM files WHERE seen_at > ? ORDER BY id DESC LIMIT ?',
                    (since, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT seen_at, scope, user_id, file_name, file_size, url, kind, raw_json FROM files ORDER BY id DESC LIMIT ?',
                    (int(limit),),
                ).fetchall()
        result = []
        for row in rows:
            try:
                raw = json.loads(row[7] or '{}')
            except Exception:
                raw = {}
            result.append(dict(
                seen_at=row[0], scope=row[1], user_id=row[2], file_name=row[3], file_size=row[4],
                url=row[5], kind=row[6], message_text=str(raw.get('message_text') or ''), raw=raw,
            ))
        return result

    def recent_images(self, scope: str, limit: int = 10) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                '''SELECT id, format, width, height, size, has_ai_metadata, ai_source, kept_path, retention_reason
                   FROM images WHERE scope = ? ORDER BY id DESC LIMIT ?''',
                (scope, int(limit)),
            ).fetchall()
        return [
            {
                'id': row[0],
                'format': row[1],
                'width': row[2],
                'height': row[3],
                'size': row[4],
                'has_ai_metadata': bool(row[5]),
                'ai_source': row[6],
                'kept_path': row[7],
                'retention_reason': row[8],
            }
            for row in rows
        ]

    def recent_images_all(self, limit: int = 10) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                """SELECT id, scope, format, width, height, size, has_ai_metadata, ai_source, kept_path, retention_reason
                   FROM images ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [
            {
                'id': row[0],
                'scope': row[1],
                'format': row[2],
                'width': row[3],
                'height': row[4],
                'size': row[5],
                'has_ai_metadata': bool(row[6]),
                'ai_source': row[7],
                'kept_path': row[8],
                'retention_reason': row[9],
            }
            for row in rows
        ]

    def image_records_with_paths(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT id, kept_path, retention_reason, has_ai_metadata FROM images WHERE kept_path IS NOT NULL ORDER BY id'
            ).fetchall()
        return [{'id': r[0], 'kept_path': r[1], 'retention_reason': r[2], 'has_ai_metadata': bool(r[3])} for r in rows]

    def latest_candidate_image(self, scope: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                '''SELECT id, sha256, kept_path, size, width, height, format, has_ai_metadata FROM images
                   WHERE scope = ? AND retention_reason = 'candidate' AND kept_path IS NOT NULL
                   ORDER BY id DESC LIMIT 1''',
                (scope,),
            ).fetchone()
        if not row:
            return None
        return {
            'id': row[0], 'sha256': row[1], 'kept_path': row[2], 'size': row[3],
            'width': row[4], 'height': row[5], 'format': row[6], 'has_ai_metadata': bool(row[7]),
        }

    def update_image_retention(self, image_id: int, *, kept_path: str | None, retention_reason: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET kept_path = ?, retention_reason = ? WHERE id = ?', (kept_path, retention_reason, int(image_id)))
            conn.commit()

    def clear_image_path(self, kept_path: str | Path) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET kept_path = NULL WHERE kept_path = ?', (str(kept_path),))
            conn.commit()

    def clear_missing_image_paths(self, base_dir: str | Path) -> int:
        base_dir = Path(base_dir)
        changed = 0
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute('SELECT id, kept_path FROM images WHERE kept_path IS NOT NULL').fetchall()
            for image_id, kept_path in rows:
                path = Path(kept_path)
                if not path.is_absolute():
                    path = base_dir / path
                if not path.exists():
                    conn.execute('UPDATE images SET kept_path = NULL WHERE id = ?', (image_id,))
                    changed += 1
            conn.commit()
        return changed

    def last_daily_report_sent_at(self) -> str | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT sent_at FROM daily_reports ORDER BY sent_at DESC LIMIT 1').fetchone()
        return str(row[0]) if row and row[0] else None

    def mark_daily_report_sent(self, report_date: str, content: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('INSERT OR REPLACE INTO daily_reports (report_date, content) VALUES (?, ?)', (report_date, content))
            conn.commit()

    def has_daily_report(self, report_date: str) -> bool:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT 1 FROM daily_reports WHERE report_date = ?', (report_date,)).fetchone()
        return bool(row)

    def get_history_cursor(self, group_id: str | int) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT group_id, newest_seq, oldest_seq, updated_at FROM history_cursors WHERE group_id = ?',
                (str(group_id),),
            ).fetchone()
        if not row:
            return None
        return {'group_id': row[0], 'newest_seq': row[1], 'oldest_seq': row[2], 'updated_at': row[3]}

    def update_history_cursor(self, group_id: str | int, *, newest_seq: str | None = None, oldest_seq: str | None = None) -> None:
        current = self.get_history_cursor(group_id) or {'newest_seq': None, 'oldest_seq': None}
        newest = str(newest_seq) if newest_seq is not None else current.get('newest_seq')
        oldest = str(oldest_seq) if oldest_seq is not None else current.get('oldest_seq')
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                '''INSERT INTO history_cursors (group_id, newest_seq, oldest_seq, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(group_id) DO UPDATE SET
                     newest_seq=excluded.newest_seq,
                     oldest_seq=excluded.oldest_seq,
                     updated_at=CURRENT_TIMESTAMP''',
                (str(group_id), newest, oldest),
            )
            conn.commit()

    def record_ai_context_batch(self, *, scope: str, start_message_id: int, end_message_id: int, model: str, summary: str, raw_json: str = '') -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                '''INSERT INTO ai_context_batches (scope, start_message_id, end_message_id, model, summary, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (scope, int(start_message_id), int(end_message_id), model, summary, raw_json),
            )
            conn.commit()

    def recent_ai_context_batches(self, *, scope: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = 'SELECT id, created_at, scope, start_message_id, end_message_id, model, summary, raw_json FROM ai_context_batches'
        args: list[Any] = []
        if scope:
            sql += ' WHERE scope = ?'
            args.append(scope)
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(limit)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def last_ai_context_end_message_id(self, scope: str) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT COALESCE(MAX(end_message_id), 0) FROM ai_context_batches WHERE scope = ?', (scope,)).fetchone()
        return int(row[0] or 0)

    def max_message_id(self, scope: str) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT COALESCE(MAX(id), 0) FROM messages WHERE scope = ?', (scope,)).fetchone()
        return int(row[0] or 0)

    def count_messages_after(self, scope: str, after_id: int) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT COUNT(*) FROM messages WHERE scope = ? AND id > ?', (scope, int(after_id))).fetchone()
        return int(row[0] or 0)

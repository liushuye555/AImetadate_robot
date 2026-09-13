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
  saved_category TEXT,
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

CREATE TABLE IF NOT EXISTS link_metadata (
  url_key TEXT PRIMARY KEY,
  resolved_url TEXT,
  title TEXT,
  description TEXT,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
  error TEXT
);

CREATE TABLE IF NOT EXISTS custom_collections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  rule TEXT,
  scope TEXT,
  user_id TEXT,
  text TEXT,
  images_json TEXT,
  links_json TEXT,
  files_json TEXT,
  message_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_custom_rule_id ON custom_collections(rule, id);

CREATE TABLE IF NOT EXISTS image_hashes (
  sha256 TEXT PRIMARY KEY,
  phash TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS link_judges (
  url_key TEXT PRIMARY KEY,
  purpose TEXT,
  tokens INTEGER,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relay_log (
  key TEXT PRIMARY KEY,
  kind TEXT,
  scope TEXT,
  text TEXT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relay_seen (
  scope TEXT,
  content_hash TEXT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (scope, content_hash)
);

CREATE TABLE IF NOT EXISTS chat_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT,
  user_id TEXT,
  role TEXT,
  text TEXT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_turns_user ON chat_turns(scope, user_id, id);

CREATE TABLE IF NOT EXISTS favorites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  content_hash TEXT,
  forward_id TEXT,
  summary TEXT,
  nodes_json TEXT,
  seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id, id);

CREATE TABLE IF NOT EXISTS prompt_judges (
  prompt_hash TEXT PRIMARY KEY,
  verdict INTEGER,
  tokens INTEGER,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discussion_judges (
  text_hash TEXT PRIMARY KEY,
  verdict INTEGER,
  tokens INTEGER,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
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
        relay_cols = {row[1] for row in conn.execute('PRAGMA table_info(relay_log)').fetchall()}
        if 'scope' not in relay_cols:
            conn.execute('ALTER TABLE relay_log ADD COLUMN scope TEXT')
        if 'text' not in relay_cols:
            conn.execute('ALTER TABLE relay_log ADD COLUMN text TEXT')
        hash_cols = {row[1] for row in conn.execute('PRAGMA table_info(image_hashes)').fetchall()}
        if 'xfq_ratio' not in hash_cols:
            conn.execute('ALTER TABLE image_hashes ADD COLUMN xfq_ratio REAL')
        if 'xfq_layers' not in hash_cols:
            conn.execute('ALTER TABLE image_hashes ADD COLUMN xfq_layers INTEGER')
        if 'xfq_obfuscated' not in hash_cols:
            conn.execute('ALTER TABLE image_hashes ADD COLUMN xfq_obfuscated INTEGER')
        if 'xfq_confidence' not in hash_cols:
            conn.execute('ALTER TABLE image_hashes ADD COLUMN xfq_confidence TEXT')

        image_cols = {row[1] for row in conn.execute('PRAGMA table_info(images)').fetchall()}
        if 'restored_path' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN restored_path TEXT')
        if 'deobfuscated' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN deobfuscated INTEGER DEFAULT 0')
        if 'vision_checked' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN vision_checked INTEGER DEFAULT 0')
        if 'vision_verdict' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN vision_verdict TEXT')
        if 'bound_prompt' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN bound_prompt TEXT')
        if 'prompt_key' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN prompt_key TEXT')
        if 'context_reason' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN context_reason TEXT')
        if 'saved_category' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN saved_category TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_images_saved_category ON images(saved_category, id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_images_prompt_key ON images(prompt_key)')
        metadata_cols = {row[1] for row in conn.execute('PRAGMA table_info(link_metadata)').fetchall()}
        if 'resolved_url' not in metadata_cols:
            conn.execute('ALTER TABLE link_metadata ADD COLUMN resolved_url TEXT')

    def record_message(self, *, scope: str, user_id: str, text: str, raw: dict[str, Any], collect_links: bool = True) -> list[str]:
        links = extract_links(text)
        message_key = canonical_message_key(raw)
        with closing(sqlite3.connect(self.path)) as conn:
            # INSERT OR IGNORE：历史消息追赶与实时事件可能并发写入同一消息，
            # 先查后插存在竞态窗口（UNIQUE 约束冲突会让整个 handle_event 失败）
            cur = conn.execute(
                'INSERT OR IGNORE INTO messages (scope, user_id, text, links_json, raw_json, message_key) VALUES (?, ?, ?, ?, ?, ?)',
                (scope, str(user_id), text, json.dumps(links, ensure_ascii=False), json.dumps(raw, ensure_ascii=False), message_key),
            )
            inserted = cur.rowcount > 0
            if inserted and collect_links:
                for url in links:
                    conn.execute(
                        'INSERT INTO links (scope, user_id, url, message_text, quoted_text, kind) VALUES (?, ?, ?, ?, ?, ?)',
                        (scope, str(user_id), url, text, '', 'link'),
                    )
            conn.commit()
        return links if inserted else []

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
            digest = result.get('sha256')
            kept_path = result.get('kept_path')
            if digest and kept_path and result.get('retention_reason') != 'candidate':
                conn.execute('UPDATE images SET kept_path = ? WHERE sha256 = ? AND kept_path IS NOT NULL', (kept_path, digest))
            conn.execute(
                '''INSERT INTO images (
                  scope, user_id, url, sha256, size, format, width, height, metadata_keys_json,
                  has_ai_metadata, ai_source, text_excerpt, kept_path, retention_reason, saved_category, restored_path,
                  deobfuscated, bound_prompt, prompt_key, context_reason, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    scope,
                    str(user_id),
                    result.get('url'),
                    digest,
                    result.get('size'),
                    result.get('format'),
                    result.get('width'),
                    result.get('height'),
                    json.dumps(result.get('metadata_keys') or [], ensure_ascii=False),
                    1 if result.get('has_ai_metadata') else 0,
                    result.get('ai_source'),
                    result.get('text_excerpt'),
                    kept_path,
                    result.get('retention_reason'),
                    result.get('saved_category'),
                     result.get('restored_path'),
                    1 if result.get('deobfuscated') else 0,
                    result.get('bound_prompt'),
                    result.get('prompt_key'),
                    result.get('context_reason'),
                    json.dumps(raw, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_image_record(self, image_id: int) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                '''SELECT id, scope, url, sha256, size, format, width, height, metadata_keys_json,
                          has_ai_metadata, ai_source, text_excerpt, kept_path, retention_reason,
                          saved_category, prompt_key, raw_json
                   FROM images WHERE id = ?''',
                (int(image_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(row[16] or '{}')
        except Exception:
            raw = {}
        try:
            metadata_keys = json.loads(row[8] or '[]')
        except Exception:
            metadata_keys = []
        return {
            'id': row[0], 'scope': row[1] or '', 'url': row[2] or '', 'sha256': row[3] or '', 'size': row[4] or 0,
            'format': row[5] or '', 'width': row[6], 'height': row[7],
            'metadata_keys': metadata_keys, 'has_ai_metadata': bool(row[9]),
            'ai_source': row[10] or '', 'text_excerpt': row[11] or '', 'kept_path': row[12] or '',
            'retention_reason': row[13] or '', 'saved_category': row[14] or '', 'prompt_key': row[15] or '', 'raw': raw,
        }


    def same_batch_image_records(self, image_id: int) -> list[dict[str, Any]]:
        record = self.get_image_record(int(image_id))
        if not record or not record.get('prompt_key'):
            return []
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT id FROM images WHERE scope = ? AND prompt_key = ? AND id <> ?"
                " AND retention_reason = 'ai_metadata' AND kept_path IS NOT NULL ORDER BY id",
                (str(record.get('scope') or ''), str(record['prompt_key']), int(image_id)),
            ).fetchall()
        return [candidate for row in rows
                if (candidate := self.get_image_record(int(row[0]))) is not None]

    def update_repaired_image(self, image_id: int, result: dict[str, Any]) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                '''UPDATE images SET
                   url = ?, sha256 = ?, size = ?, format = ?, width = ?, height = ?,
                   metadata_keys_json = ?, has_ai_metadata = ?, ai_source = ?, text_excerpt = ?,
                   prompt_key = ?, kept_path = ?
                   WHERE id = ?''',
                (
                    str(result.get('url') or ''), str(result.get('sha256') or ''),
                    int(result.get('size') or 0), str(result.get('format') or ''),
                    result.get('width'), result.get('height'),
                    json.dumps(result.get('metadata_keys') or [], ensure_ascii=False),
                    1 if result.get('has_ai_metadata') else 0,
                    str(result.get('ai_source') or ''), str(result.get('text_excerpt') or ''),
                    str(result.get('prompt_key') or ''), str(result.get('kept_path') or ''),
                    int(image_id),
                ),
            )
            conn.commit()

    def update_image_restored(self, image_id: int, restored_path: str | None) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'UPDATE images SET restored_path = ? WHERE id = ?',
                (restored_path, int(image_id)),
            )
            conn.commit()

    def mark_image_deobfuscated(self, image_id: int, *, kept_path: str, restored_path: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'UPDATE images SET kept_path=?, restored_path=?, deobfuscated=1 WHERE id=?',
                (kept_path, restored_path, int(image_id)),
            )
            conn.commit()

    def backfill_prompt_key(self, image_id: int, prompt_key: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET prompt_key=? WHERE id=?', (prompt_key, int(image_id)))
            conn.commit()

    def get_link_judge(self, url_key: str) -> str | None:
        if not url_key:
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT purpose FROM link_judges WHERE url_key = ?',
                (url_key,),
            ).fetchone()
        return str(row[0]) if row else None

    def set_link_judge(self, url_key: str, purpose: str, tokens: int = 0) -> None:
        if not url_key:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO link_judges (url_key, purpose, tokens) VALUES (?, ?, ?) '
                'ON CONFLICT(url_key) DO UPDATE SET purpose = excluded.purpose, '
                'tokens = excluded.tokens, updated_at = CURRENT_TIMESTAMP',
                (url_key, purpose, int(tokens)),
            )
            conn.commit()

    def relay_seen(self, key: str, *, hours: int = 24) -> bool:
        """搬运去重：key 在最近 hours 小时内已转发过。"""
        if not key:
            return False
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM relay_log WHERE key = ? AND seen_at >= datetime('now', ?)",
                (key, f'-{max(1, int(hours))} hours'),
            ).fetchone()
        return row is not None

    def relay_log(self, key: str, kind: str = '', scope: str = '', text: str = '') -> None:
        if not key:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO relay_log (key, kind, scope, text) VALUES (?, ?, ?, ?)',
                (key, str(kind or ''), str(scope or ''), str(text or '')),
            )
            conn.execute("DELETE FROM relay_log WHERE seen_at < datetime('now', '-72 hours')")
            conn.commit()

    def record_forward_seen(self, scope: str, content_hash: str) -> None:
        """记录某群出现过该合并消息内容（用于"别人发过的不重复搬"）。"""
        if not content_hash:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO relay_seen (scope, content_hash) VALUES (?, ?) '
                'ON CONFLICT(scope, content_hash) DO UPDATE SET seen_at = CURRENT_TIMESTAMP',
                (str(scope or ''), str(content_hash)),
            )
            conn.execute("DELETE FROM relay_seen WHERE seen_at < datetime('now', '-72 hours')")
            conn.commit()

    def forward_seen_in(self, scope: str, content_hash: str, *, hours: int = 24) -> bool:
        """目标群在最近 hours 小时内是否已出现过该合并消息内容。"""
        if not content_hash:
            return False
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM relay_seen WHERE scope = ? AND content_hash = ? "
                "AND seen_at >= datetime('now', ?)",
                (str(scope or ''), str(content_hash), f'-{max(1, int(hours))} hours'),
            ).fetchone()
        return row is not None

    def record_chat_turn(self, scope: str, user_id: str, role: str, text: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO chat_turns (scope, user_id, role, text) VALUES (?, ?, ?, ?)',
                (str(scope), str(user_id), str(role), str(text or '')),
            )
            conn.commit()

    def recent_chat_turns(self, scope: str, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT role, text, seen_at FROM chat_turns '
                'WHERE scope = ? AND user_id = ? ORDER BY id DESC LIMIT ?',
                (str(scope), str(user_id), int(limit)),
            ).fetchall()
        return [
            dict(role=r[0], text=r[1] or '', seen_at=r[2] or '')
            for r in reversed(rows)
        ]

    def save_favorite(self, *, user_id: str, content_hash: str, forward_id: str = '',
                      summary: str = '', nodes_json: str = '') -> bool:
        """保存私聊收藏；同一用户同一内容不重复存。"""
        if not content_hash:
            return False
        with closing(sqlite3.connect(self.path)) as conn:
            dup = conn.execute(
                'SELECT 1 FROM favorites WHERE user_id = ? AND content_hash = ?',
                (str(user_id), str(content_hash)),
            ).fetchone()
            if dup:
                return False
            conn.execute(
                'INSERT INTO favorites (user_id, content_hash, forward_id, summary, nodes_json) VALUES (?, ?, ?, ?, ?)',
                (str(user_id), str(content_hash), str(forward_id or ''),
                 str(summary or ''), str(nodes_json or '')),
            )
            conn.commit()
        return True

    def list_favorites(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT id, seen_at, summary, forward_id FROM favorites '
                'WHERE user_id = ? ORDER BY id DESC LIMIT ?',
                (str(user_id), int(limit)),
            ).fetchall()
        return [dict(id=r[0], seen_at=r[1] or '', summary=r[2] or '', forward_id=r[3] or '') for r in rows]

    def get_prompt_judge(self, prompt_hash: str) -> bool | None:
        if not prompt_hash:
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT verdict FROM prompt_judges WHERE prompt_hash = ?',
                (prompt_hash,),
            ).fetchone()
        return bool(row[0]) if row else None

    def set_prompt_judge(self, prompt_hash: str, verdict: bool, tokens: int = 0) -> None:
        if not prompt_hash:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO prompt_judges (prompt_hash, verdict, tokens) VALUES (?, ?, ?) '
                'ON CONFLICT(prompt_hash) DO UPDATE SET verdict = excluded.verdict, '
                'tokens = excluded.tokens, updated_at = CURRENT_TIMESTAMP',
                (prompt_hash, 1 if verdict else 0, int(tokens)),
            )
            conn.commit()

    def get_discussion_judge(self, text_hash: str) -> bool | None:
        if not text_hash:
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT verdict FROM discussion_judges WHERE text_hash = ?',
                (text_hash,),
            ).fetchone()
        return bool(row[0]) if row else None

    def set_discussion_judge(self, text_hash: str, verdict: bool, tokens: int = 0) -> None:
        if not text_hash:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO discussion_judges (text_hash, verdict, tokens) VALUES (?, ?, ?) '
                'ON CONFLICT(text_hash) DO UPDATE SET verdict = excluded.verdict, '
                'tokens = excluded.tokens, updated_at = CURRENT_TIMESTAMP',
                (text_hash, 1 if verdict else 0, int(tokens)),
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

    def recent_records_before(self, scope: str, before_id: int | None, limit: int = 6) -> list[dict[str, Any]]:
        """以指定消息 id 为锚点的附近消息记录（含该消息及其前 limit-1 条）。

        与 recent_records 结构一致（含 quoted_text / reply_to_message_id），
        供历史图片绑定判定使用——取图片当时附近的窗口，而非当前最新消息。
        """
        with closing(sqlite3.connect(self.path)) as conn:
            if before_id is not None:
                rows = conn.execute(
                    'SELECT id, seen_at, user_id, text, links_json, raw_json '
                    'FROM messages WHERE scope = ? AND id <= ? ORDER BY id DESC LIMIT ?',
                    (scope, int(before_id), int(limit)),
                ).fetchall()
                context_rows = conn.execute(
                    'SELECT text, raw_json FROM messages WHERE scope = ? AND id <= ? ORDER BY id DESC LIMIT ?',
                    (scope, int(before_id), max(int(limit) * 5, 500)),
                ).fetchall()
            else:
                return self.recent_records(scope, limit=limit)
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

    def recent_link_rows(self, limit: int = 10000) -> list[dict[str, Any]]:
        """轻量链接行（站点画像用）：只取 url 与上下文。"""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT url, message_text, quoted_text FROM links ORDER BY id DESC LIMIT ?',
                (int(limit),),
            ).fetchall()
        return [dict(url=r[0], message_text=r[1] or '', quoted_text=r[2] or '') for r in rows]

    def link_metadata_map(self, limit: int = 20000) -> dict[str, tuple[str, str]]:
        """url_key → (title, description)，一次查询避免逐条连接。"""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT url_key, title, description FROM link_metadata "
                "WHERE title IS NOT NULL AND title != '' LIMIT ?",
                (int(limit),),
            ).fetchall()
        return {r[0]: (r[1] or '', r[2] or '') for r in rows}

    def get_link_metadata(self, url_key: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT url_key, resolved_url, title, description, fetched_at, error FROM link_metadata WHERE url_key = ?',
                (str(url_key),),
            ).fetchone()
        if not row:
            return None
        return {
            'url_key': row[0], 'resolved_url': row[1] or '', 'title': row[2] or '',
            'description': row[3] or '', 'fetched_at': row[4] or '', 'error': row[5] or '',
        }

    def save_link_metadata(
        self,
        url_key: str,
        title: str,
        description: str,
        error: str = '',
        resolved_url: str = '',
    ) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                '''INSERT INTO link_metadata (url_key, resolved_url, title, description, fetched_at, error)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                   ON CONFLICT(url_key) DO UPDATE SET resolved_url = excluded.resolved_url,
                     title = excluded.title, description = excluded.description,
                     fetched_at = excluded.fetched_at, error = excluded.error''',
                (
                    str(url_key), str(resolved_url or ''), str(title or ''),
                    str(description or ''), str(error or ''),
                ),
            )
            conn.commit()

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
            rows = conn.execute('SELECT id FROM images WHERE kept_path IS NOT NULL ORDER BY id').fetchall()
        return [record for row in rows if (record := self.get_image_record(int(row[0]))) is not None]

    def has_saved_image(self, sha256: str, category: str) -> bool:
        if not sha256 or not category:
            return False
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM images WHERE sha256 = ? AND retention_reason = 'chat_record_saved' AND saved_category = ? LIMIT 1",
                (str(sha256), str(category)),
            ).fetchone()
        return row is not None

    def saved_image_records(self, user_id: str | None = None, *, category: str | None = None,
                            limit: int = 5000) -> list[dict[str, Any]]:
        sql = (
            'SELECT id, scope, user_id, seen_at, url, sha256, size, format, width, height, '
            'kept_path, retention_reason, saved_category, raw_json '
            "FROM images WHERE retention_reason = 'chat_record_saved'"
        )
        args: list[Any] = []
        if user_id is not None:
            sql += ' AND user_id = ?'
            args.append(str(user_id))
        if category is not None:
            sql += ' AND saved_category = ?'
            args.append(str(category))
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(int(limit))
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(sql, args).fetchall()
        result = []
        for row in rows:
            try:
                raw = json.loads(row[13] or '{}')
            except Exception:
                raw = {}
            result.append({
                'id': row[0], 'scope': row[1], 'user_id': row[2], 'seen_at': row[3] or '',
                'url': row[4] or '', 'sha256': row[5] or '', 'size': row[6] or 0,
                'format': row[7] or '', 'width': row[8], 'height': row[9],
                'kept_path': row[10] or '', 'retention_reason': row[11] or '',
                'saved_category': row[12] or '', 'raw': raw,
            })
        return result

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

    def replace_image_path(self, old_path: str | Path, new_path: str | Path) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET kept_path = ? WHERE kept_path = ?', (str(new_path), str(old_path)))
            conn.commit()

    def set_image_path_for_sha(self, sha256: str, path: str | Path) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET kept_path = ? WHERE sha256 = ?', (str(path), str(sha256)))
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

    def record_custom_collection(self, *, rule: str, scope: str, user_id: str, text: str,
                                 images: list[str] | None = None, links: list[str] | None = None,
                                 files: list[str] | None = None, message_key: str | None = None) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            if message_key:
                existing = conn.execute(
                    'SELECT 1 FROM custom_collections WHERE rule = ? AND message_key = ?',
                    (rule, message_key),
                ).fetchone()
                if existing:
                    return
            conn.execute(
                'INSERT INTO custom_collections (rule, scope, user_id, text, images_json, links_json, files_json, message_key) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (rule, str(scope), str(user_id), text,
                 json.dumps(images or [], ensure_ascii=False),
                 json.dumps(links or [], ensure_ascii=False),
                 json.dumps(files or [], ensure_ascii=False),
                 message_key),
            )
            conn.commit()

    def recent_custom_collections(self, rule: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            if rule:
                rows = conn.execute(
                    'SELECT rule, scope, user_id, text, images_json, links_json, files_json, seen_at '
                    'FROM custom_collections WHERE rule = ? ORDER BY id DESC LIMIT ?',
                    (rule, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT rule, scope, user_id, text, images_json, links_json, files_json, seen_at '
                    'FROM custom_collections ORDER BY id DESC LIMIT ?',
                    (limit,),
                ).fetchall()
        items = []
        for rule_name, scope, user_id, text, images_json, links_json, files_json, seen_at in rows:
            items.append({
                'rule': rule_name,
                'scope': scope,
                'user_id': user_id,
                'text': text,
                'images': json.loads(images_json or '[]'),
                'links': json.loads(links_json or '[]'),
                'files': json.loads(files_json or '[]'),
                'seen_at': seen_at,
            })
        return items

    def count_image_occurrences(self, scope: str, sha256: str) -> int:
        """统计某群内同一图片（sha256）已出现的次数。"""
        if not sha256:
            return 0
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT COUNT(*) FROM images WHERE scope = ? AND sha256 = ?',
                (scope, sha256),
            ).fetchone()
        return int(row[0]) if row else 0

    def save_image_hash(self, sha256: str, phash: int) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO image_hashes (sha256, phash) VALUES (?, ?) '
                'ON CONFLICT(sha256) DO UPDATE SET phash = excluded.phash, updated_at = CURRENT_TIMESTAMP',
                (sha256, str(int(phash))),
            )
            conn.commit()

    def save_obfuscation_score(
        self, sha256: str, *, ratio: float, layers: int | None,
        obfuscated: bool, confidence: str | None = None,
    ) -> None:
        """缓存小番茄混淆检测结果，避免重分类时重复分析。"""
        if not sha256:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'INSERT INTO image_hashes (sha256, xfq_ratio, xfq_layers, xfq_obfuscated, xfq_confidence) '
                'VALUES (?, ?, ?, ?, ?) '
                'ON CONFLICT(sha256) DO UPDATE SET xfq_ratio = excluded.xfq_ratio, '
                'xfq_layers = excluded.xfq_layers, xfq_obfuscated = excluded.xfq_obfuscated, '
                'xfq_confidence = excluded.xfq_confidence, '
                'updated_at = CURRENT_TIMESTAMP',
                (sha256, round(float(ratio), 4), layers, 1 if obfuscated else 0, confidence),
            )
            conn.commit()

    def obfuscation_score(self, sha256: str) -> tuple[float, int | None, bool, str | None] | None:
        """返回缓存的 (ratio, layers, obfuscated, confidence)；未检测过返回 None。"""
        if not sha256:
            return None
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                'SELECT xfq_ratio, xfq_layers, xfq_obfuscated, xfq_confidence FROM image_hashes WHERE sha256 = ?',
                (sha256,),
            ).fetchone()
        if not row or row[0] is None:
            return None
        return (float(row[0]), int(row[1]) if row[1] is not None else None, bool(row[2]), row[3])

    def set_vision_verdict(self, verdict: str, image_id: int) -> None:
        """缓存视觉复核结果（一张图只花一次 token）。"""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'UPDATE images SET vision_verdict = ?, vision_checked = 1 WHERE id = ?',
                (verdict, int(image_id)),
            )
            conn.commit()

    def vision_unchecked_images(self, *, categories: tuple[str, ...], limit: int = 20) -> list[tuple]:
        """未做过视觉复核的图：(id, sha256, kept_path, context, category)。"""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ', '.join('?' for _ in categories)
            rows = conn.execute(
                "SELECT id, COALESCE(sha256, ''), COALESCE(kept_path, ''), "
                "COALESCE(bound_prompt, text_excerpt, ''), retention_reason FROM images "
                "WHERE retention_reason IN (" + placeholders + ") "
                "AND kept_path IS NOT NULL "
                "AND (vision_checked IS NULL OR vision_checked = 0) "
                "ORDER BY id DESC LIMIT ?",
                (*categories, int(limit)),
            ).fetchall()
        return [(r['id'], r[1], r[2], r[3], r['retention_reason']) for r in rows]

    def demote_image_to_candidate(self, image_id: int) -> None:
        """视觉判定图不对：降到 04_候选待观察（数据不删，报告可见）。"""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "UPDATE images SET retention_reason = 'candidate', "
                "bound_prompt = NULL, vision_checked = 1 WHERE id = ?",
                (int(image_id),),
            )
            conn.commit()

    def archive_hashes(self, limit: int = 20000) -> list[tuple[int, str]]:
        """返回 AI 归档图片的 (phash, sha256) 列表。"""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                'SELECT h.phash, h.sha256 FROM image_hashes h '
                'JOIN images i ON i.sha256 = h.sha256 AND i.retention_reason = ? '
                'WHERE h.phash IS NOT NULL ORDER BY i.id DESC LIMIT ?',
                ('ai_metadata', limit),
            ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows if row[0] is not None and str(row[0]).strip()]

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

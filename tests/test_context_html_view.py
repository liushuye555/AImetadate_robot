import sqlite3
from pathlib import Path

from qq_onebot_whitelist.build_image_view import build_view


def test_nearby_ai_context_builds_html(tmp_path):
    data = tmp_path / 'data'
    db = data / 'bot.db'
    img = data / 'images' / 'ai' / 'aa' / 'img.png'
    img.parent.mkdir(parents=True)
    img.write_bytes(b'png')
    conn = sqlite3.connect(db)
    conn.executescript('''
    CREATE TABLE images (
      id INTEGER PRIMARY KEY, seen_at TEXT DEFAULT CURRENT_TIMESTAMP, scope TEXT, user_id TEXT,
      url TEXT, sha256 TEXT, size INTEGER, format TEXT, width INTEGER, height INTEGER,
      metadata_keys_json TEXT, has_ai_metadata INTEGER, ai_source TEXT, text_excerpt TEXT,
      kept_path TEXT, retention_reason TEXT, raw_json TEXT
    );
    CREATE TABLE ai_context_batches (
      id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, scope TEXT,
      start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT
    );
    ''')
    conn.execute('INSERT INTO images (id, scope, user_id, sha256, format, width, height, kept_path, retention_reason, text_excerpt, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                 (1, 'group:1', 'u', 'sha', 'PNG', 100, 200, str(img), 'nearby_ai_context', '附近提示词', '{"message_db_id": 10}'))
    conn.execute('INSERT INTO ai_context_batches (scope, start_message_id, end_message_id, model, summary, raw_json) VALUES (?,?,?,?,?,?)',
                 ('group:1', 1, 20, 'deepseek-v4-flash', '## DS总结\n\n- **提示词**与模型', '{}'))
    conn.execute('INSERT INTO ai_context_batches (scope, start_message_id, end_message_id, model, summary, raw_json) VALUES (?,?,?,?,?,?)',
                 ('group:1', 21, 99, 'deepseek-v4-flash', '不应显示的最新摘要', '{}'))
    conn.commit(); conn.close()
    counts = build_view(tmp_path)
    assert counts['03_AI上下文'] == 1
    html = data / 'view' / '03_AI上下文' / 'index.html'
    assert html.exists()
    text = html.read_text(encoding='utf-8')
    assert 'DS总结' in text
    assert '附近提示词' in text
    assert '<img' in text
    assert '<h2>DS总结</h2>' in text
    assert '<strong>提示词</strong>' in text
    assert '<details>' in text
    assert '不应显示的最新摘要' not in text

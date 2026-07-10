import sqlite3

from qq_onebot_whitelist.build_image_view import build_view


def create_db(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    conn = sqlite3.connect(data / 'bot.db')
    conn.executescript('''
    CREATE TABLE messages (id INTEGER PRIMARY KEY, scope TEXT, raw_json TEXT);
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
    return conn


def add_image(conn, tmp_path, image_id, scope, seen_at, raw_json, excerpt):
    image = tmp_path / 'data' / 'images' / f'{image_id}.png'
    image.parent.mkdir(exist_ok=True)
    image.write_bytes(f'image-{image_id}'.encode())
    conn.execute(
        '''INSERT INTO images
           (id, seen_at, scope, user_id, sha256, format, width, height, kept_path,
            retention_reason, text_excerpt, raw_json)
           VALUES (?, ?, ?, 'u', ?, 'PNG', 100, 200, ?, 'nearby_ai_context', ?, ?)''',
        (image_id, seen_at, scope, f'sha-{image_id}', str(image), excerpt, raw_json),
    )


def test_context_index_uses_directory_and_iframe_without_full_summaries(tmp_path):
    conn = create_db(tmp_path)
    conn.execute(
        "INSERT INTO messages VALUES (1, 'group:1', ?)",
        ('{"group_name":"绘图一群"}',),
    )
    conn.execute(
        '''INSERT INTO ai_context_batches
           (id, created_at, scope, start_message_id, end_message_id, model, summary, raw_json)
           VALUES (11, '2026-07-08 12:00:00', 'group:1', 1, 20, 'm',
                   '## 精确批次摘要\n\n- **提示词**', '{"quality":{"value_level":"high"}}')'''
    )
    conn.execute(
        '''INSERT INTO ai_context_batches
           (id, created_at, scope, start_message_id, end_message_id, model, summary, raw_json)
           VALUES (12, '2026-07-09 12:00:00', 'group:2', 21, 99, 'm',
                   '绝不能绑定给旧图片的最新摘要', '{}')'''
    )
    add_image(conn, tmp_path, 1, 'group:1', '2026-07-08 13:00:00', '{"message_db_id":10}', '精确图片上下文')
    add_image(conn, tmp_path, 2, 'group:2', '2026-07-09 13:00:00', '{}', '旧图片上下文')
    conn.commit()
    conn.close()

    counts = build_view(tmp_path)

    context_dir = tmp_path / 'data' / 'view' / '03_AI上下文'
    index_text = (context_dir / 'index.html').read_text(encoding='utf-8')
    assert counts['03_AI上下文'] == 2
    assert '<iframe' in index_text
    assert '<details' in index_text
    assert '绘图一群' in index_text
    assert '2026-07-08' in index_text
    assert '2026-07-09' in index_text
    assert '精确批次摘要' not in index_text
    assert '绝不能绑定给旧图片的最新摘要' not in index_text

    batch_text = (context_dir / 'batches' / '11.html').read_text(encoding='utf-8')
    assert '<h2>精确批次摘要</h2>' in batch_text
    assert '<strong>提示词</strong>' in batch_text
    assert '精确图片上下文' in batch_text
    assert '%231_' in batch_text
    assert '旧图片上下文' not in batch_text

    history_text = (context_dir / 'history' / 'group_2' / '2026-07-09.html').read_text(encoding='utf-8')
    assert '旧图片上下文' in history_text
    assert '%232_' in history_text
    assert '绝不能绑定给旧图片的最新摘要' not in history_text

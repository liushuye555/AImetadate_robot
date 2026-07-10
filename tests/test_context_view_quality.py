import sqlite3

from qq_onebot_whitelist.build_image_view import build_view
from qq_onebot_whitelist.context_view import _date


def test_context_dates_convert_sqlite_utc_to_local_timezone():
    assert _date('2026-07-09 16:30:00') == '2026-07-10'


def test_context_batches_split_by_quality_and_hide_low(tmp_path):
    data = tmp_path / 'data'
    images = data / 'images'
    images.mkdir(parents=True)
    conn = sqlite3.connect(data / 'bot.db')
    conn.executescript('''
    CREATE TABLE images (
      id INTEGER PRIMARY KEY, seen_at TEXT, scope TEXT, user_id TEXT, url TEXT, sha256 TEXT,
      size INTEGER, format TEXT, width INTEGER, height INTEGER, metadata_keys_json TEXT,
      has_ai_metadata INTEGER, ai_source TEXT, text_excerpt TEXT, kept_path TEXT,
      retention_reason TEXT, raw_json TEXT
    );
    CREATE TABLE ai_context_batches (
      id INTEGER PRIMARY KEY, created_at TEXT, scope TEXT, start_message_id INTEGER,
      end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT
    );
    ''')
    qualities = {
        21: '{"quality":{"value_level":"high"}}',
        22: '{"quality":{"value_level":"review"}}',
        23: '{"quality":{"value_level":"low"}}',
        24: '{}',
    }
    for batch_id, raw_json in qualities.items():
        start = (batch_id - 20) * 10
        conn.execute(
            '''INSERT INTO ai_context_batches VALUES (?, '2026-07-10 09:00:00', 'group:9', ?, ?, 'm', ?, ?)''',
            (batch_id, start, start + 9, f'SUMMARY_{batch_id}', raw_json),
        )
        image = images / f'{batch_id}.png'
        image.write_bytes(f'IMAGE_{batch_id}'.encode())
        conn.execute(
            '''INSERT INTO images
               (id, seen_at, scope, user_id, sha256, format, width, height, kept_path,
                retention_reason, text_excerpt, raw_json)
               VALUES (?, '2026-07-10 10:00:00', 'group:9', 'u', ?, 'PNG', 100, 100,
                       ?, 'nearby_ai_context', ?, ?)''',
            (batch_id, f'sha-{batch_id}', str(image), f'IMAGE_{batch_id}', f'{{"message_db_id":{start}}}'),
        )
    conn.commit()
    conn.close()

    build_view(tmp_path)

    context_dir = data / 'view' / '03_AI上下文'
    index_text = (context_dir / 'index.html').read_text(encoding='utf-8')
    assert '高价值' in index_text
    assert '待复核' in index_text
    assert 'batches/21.html' in index_text
    assert 'batches/22.html' in index_text
    assert 'batches/24.html' in index_text
    assert 'batches/23.html' not in index_text
    assert not (context_dir / 'batches' / '23.html').exists()

    high_text = (context_dir / 'batches' / '21.html').read_text(encoding='utf-8')
    review_text = (context_dir / 'batches' / '22.html').read_text(encoding='utf-8')
    default_review_text = (context_dir / 'batches' / '24.html').read_text(encoding='utf-8')
    assert 'IMAGE_21' in high_text and 'IMAGE_22' not in high_text
    assert '待复核' not in high_text
    assert '待复核' in review_text
    assert '待复核' in default_review_text
    assert (images / '23.png').exists()
    with sqlite3.connect(data / 'bot.db') as check:
        assert check.execute('SELECT COUNT(*) FROM ai_context_batches').fetchone()[0] == 4

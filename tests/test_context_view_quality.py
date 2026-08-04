import sqlite3

from qq_onebot_whitelist.context_view import _date
from qq_onebot_whitelist.context_view import build_context_view


def test_context_dates_convert_sqlite_utc_to_local_timezone():
    assert _date('2026-07-09 16:30:00') == '2026-07-10'


def test_context_batches_show_only_reusable_context_without_review_section(tmp_path):
    conn = sqlite3.connect(tmp_path / 'batches.db')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE ai_context_batches (
      id INTEGER PRIMARY KEY, created_at TEXT, scope TEXT, start_message_id INTEGER,
      end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT
    );
    ''')
    qualities = {
        21: '{"quality":{"value_level":"high"}}',
        22: '{"quality":{"value_level":"review"},"hidden":true}',
        23: '{"quality":{"value_level":"low"}}',
        24: '{"hidden":true}',
    }
    for batch_id, raw_json in qualities.items():
        start = (batch_id - 20) * 10
        conn.execute(
            '''INSERT INTO ai_context_batches VALUES (?, '2026-07-10 09:00:00', 'group:9', ?, ?, 'm', ?, ?)''',
            (batch_id, start, start + 9, f'SUMMARY_{batch_id}', raw_json),
        )
    items = [
        {
            'id': str(batch_id), 'scope': 'group:9', 'image_rel': f'{batch_id}.png',
            'meta': '2026-07-10 10:00:00 · 100x100', 'seen_at': '2026-07-10 10:00:00',
            'text_excerpt': f'IMAGE_{batch_id}', 'context_text': '',
            'message_db_id': (batch_id - 20) * 10, 'deobfuscated': False,
        }
        for batch_id in qualities
    ]
    conn.commit()

    context_dir = tmp_path / 'view' / '03_AI上下文'
    stale = context_dir / 'batches' / '999.html'
    stale.parent.mkdir(parents=True)
    stale.write_text('STALE', encoding='utf-8')

    build_context_view(conn, context_dir, items, {})
    conn.close()

    index_text = (context_dir / 'index.html').read_text(encoding='utf-8')
    assert '可复用参数' in index_text
    assert 'batches/21.html' in index_text
    assert '待复核' not in index_text
    assert 'batches/22.html' not in index_text
    assert 'batches/24.html' not in index_text
    assert 'batches/23.html' not in index_text
    assert not (context_dir / 'batches' / '22.html').exists()
    assert not (context_dir / 'batches' / '23.html').exists()
    assert not stale.exists()

    high_text = (context_dir / 'batches' / '21.html').read_text(encoding='utf-8')
    assert 'IMAGE_21' in high_text
    assert '待复核' not in high_text
    history_pages = list((context_dir / 'history').rglob('*.html'))
    history_text = ''.join(path.read_text(encoding='utf-8') for path in history_pages)
    assert 'IMAGE_22' in history_text
    assert 'IMAGE_23' in history_text
    assert 'IMAGE_24' in history_text

import sqlite3

from qq_onebot_whitelist.store import Store


def test_clear_missing_image_paths(tmp_path):
    store = Store(tmp_path / 'bot.db')
    existing = tmp_path / 'data' / 'images' / 'ai' / 'ok.png'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'x')
    missing = tmp_path / 'data' / 'images' / 'ai' / 'missing.png'
    store.record_image(scope='group:1', user_id='u', result={
        'url': 'a', 'sha256': 'sha1', 'size': 1, 'format': 'PNG', 'width': 1, 'height': 1,
        'metadata_keys': [], 'has_ai_metadata': True, 'ai_source': 'ComfyUI', 'text_excerpt': '',
        'kept_path': str(existing), 'retention_reason': 'ai_metadata'
    }, raw={})
    store.record_image(scope='group:1', user_id='u', result={
        'url': 'b', 'sha256': 'sha2', 'size': 1, 'format': 'PNG', 'width': 1, 'height': 1,
        'metadata_keys': [], 'has_ai_metadata': False, 'ai_source': '', 'text_excerpt': '',
        'kept_path': str(missing), 'retention_reason': 'candidate'
    }, raw={})
    assert store.clear_missing_image_paths(tmp_path) == 1
    conn = sqlite3.connect(tmp_path / 'bot.db')
    rows = dict(conn.execute('SELECT sha256, kept_path FROM images').fetchall())
    conn.close()
    assert rows['sha1'] == str(existing)
    assert rows['sha2'] is None

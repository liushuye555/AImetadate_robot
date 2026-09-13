from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist.summary import extract_links, summarize_records


def test_extract_links_dedupes_and_strips_punctuation():
    text = '资料 https://example.com/a?b=1，备用 https://example.com/a?b=1 还有 http://x.test/y).'
    assert extract_links(text) == ['https://example.com/a?b=1', 'http://x.test/y']


def test_extract_links_does_not_consume_following_chinese_text():
    text = '资源 https://tusi.cn/models/1025956255161707549更'
    assert extract_links(text) == ['https://tusi.cn/models/1025956255161707549']


def test_extract_links_keeps_fragment_and_encoded_query():
    text = '看 https://zhaiqi.vip/tools/#meme-generator 和 https://music.163.com/song?id=1&name=a%20b'
    assert extract_links(text) == [
        'https://zhaiqi.vip/tools/#meme-generator',
        'https://music.163.com/song?id=1&name=a%20b',
    ]


def test_store_records_messages_links_and_summarizes(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_message(scope='group:1', user_id='1001', text='第一条 https://a.test', raw={'id': 1})
    store.record_message(scope='group:1', user_id='1001', text='第二条：讨论白名单@回复', raw={'id': 2})

    records = store.recent_records('group:1', limit=10)
    links = store.recent_links('group:1', limit=10)
    summary = summarize_records(records)

    assert links == ['https://a.test']
    assert '最近 2 条消息摘要' in summary
    assert '白名单@回复' in summary


def test_image_deobfuscated_flag_and_mark(tmp_path):
    from qq_onebot_whitelist.store import Store
    db = tmp_path / "data" / "bot.db"
    store = Store(db)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "d1", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(tmp_path / "a.png"), "retention_reason": "xiaofanqie_obfuscated",
        "deobfuscated": True,
    }, raw={})
    import sqlite3
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT deobfuscated FROM images WHERE sha256='d1'").fetchone()
    conn.close()
    assert row[0] == 1

    store.mark_image_deobfuscated(1, kept_path=str(tmp_path / "r.png"), restored_path=str(tmp_path / "r.png"))
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT kept_path, restored_path, deobfuscated FROM images WHERE id=1").fetchone()
    conn.close()
    assert row == (str(tmp_path / "r.png"), str(tmp_path / "r.png"), 1)


def test_bound_prompt_and_prompt_key_columns(tmp_path):
    import sqlite3
    from qq_onebot_whitelist.store import Store
    db = tmp_path / "data" / "bot.db"
    store = Store(db)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "p1", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(tmp_path / "a.png"), "retention_reason": "prompt_bound",
        "bound_prompt": "1girl, solo",
        "prompt_key": "abc123",
    }, raw={})
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT bound_prompt, prompt_key FROM images WHERE sha256='p1'").fetchone()
    conn.close()
    assert row == ("1girl, solo", "abc123")


def test_store_migrates_saved_category_before_creating_index(tmp_path):
    import sqlite3

    db = tmp_path / 'legacy.db'
    with sqlite3.connect(db) as conn:
        conn.execute(
            '''CREATE TABLE images (
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
            )'''
        )

    Store(db)

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(images)')}
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(images)')}
    assert 'saved_category' in columns
    assert 'idx_images_saved_category' in indexes
from pathlib import Path

from qq_onebot_whitelist.build_image_view import write_view_index


def test_write_view_index_lists_categories_and_links(tmp_path):
    view = tmp_path / 'view'
    (view / '03_AI上下文').mkdir(parents=True)
    (view / '03_AI上下文' / 'index.html').write_text('x', encoding='utf-8')
    (view / '02_群友好评').mkdir(parents=True)
    (view / '02_群友好评' / 'a.jpg').write_bytes(b'x')

    write_view_index(view, {'03_AI上下文': 5, '02_群友好评': 1})

    html = (view / 'index.html').read_text(encoding='utf-8')
    assert 'resources.html' in html
    assert 'files.html' in html
    assert '03_AI%E4%B8%8A%E4%B8%8B%E6%96%87/index.html' in html
    assert '02_%E7%BE%A4%E5%8F%8B%E5%A5%BD%E8%AF%84/' in html
    assert '5 张' in html
    assert '1 张' in html


def test_build_view_single_file_with_mask_marker_and_toggle(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / "data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / "bot.db")
    conn.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
        ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
        deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT)""")
    conn.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)""")
    conn.execute("""CREATE TABLE ai_context_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, scope TEXT,
        start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT)""")
    img = tmp_path / "img.png"
    img.write_bytes(b"x" * 10)
    conn.execute(
        "INSERT INTO images (scope, user_id, format, width, height, retention_reason, kept_path, restored_path, deobfuscated) "
        "VALUES ('group:1', 'u', 'PNG', 64, 64, 'positive_feedback', ?, ?, 1)",
        (str(img), str(img)),
    )
    conn.commit()
    conn.close()

    counts = build_view(tmp_path)
    cat = tmp_path / "data" / "view" / "02_群友好评"
    files = [p.name for p in cat.rglob("*") if p.is_file() and p.name != "index.html"]
    assert len(files) == 1
    assert "_还原" in files[0]
    assert "解混淆" not in files[0]
    index = (tmp_path / "data" / "view" / "index.html").read_text(encoding="utf-8")
    assert "遮罩混淆还原图" in index
    assert "maskRestored" in index
    gallery = (cat / "index.html").read_text(encoding="utf-8")
    assert "maskRestored" in gallery
    assert "blur" in gallery

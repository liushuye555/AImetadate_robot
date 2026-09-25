"""视图按内容去重与历史重判测试。"""

import sqlite3

from PIL import Image


def make_db(tmp_path, rows):
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / 'bot.db')
    conn.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
        ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
        deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT, sha256 TEXT,
        merged_into INTEGER, saved_category TEXT, prompt_key TEXT, context_reason TEXT,
        bound_prompt TEXT, stego_state TEXT)""")
    conn.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)""")
    conn.execute("""CREATE TABLE ai_context_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, scope TEXT,
        start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT)""")
    sha_by_path: dict[str, int] = {}
    for r in rows:
        kept = r[2]
        sha_by_path.setdefault(kept, len(sha_by_path) + 1)
        conn.execute(
            "INSERT INTO images (scope, user_id, format, width, height, retention_reason, kept_path, ai_source, has_ai_metadata, sha256) "
            "VALUES (?, 'u', 'PNG', 64, 64, ?, ?, ?, 1, ?)",
            (*r, f'sha-{sha_by_path[kept]}'))
    conn.commit()
    conn.close()


def make_image(path):
    path.write_bytes(b'fake')
    Image.new('RGBA', (8, 8), (10, 20, 30, 255)).save(path)
    return path


def test_same_content_shown_once_with_occurrence_suffix(tmp_path):
    """同一张图被记 3 条（重发场景）：页面只显示 1 个，文件名带 _x3。"""
    from qq_onebot_whitelist.build_image_view import build_view

    img = make_image(tmp_path / 'a.png')
    make_db(tmp_path, [
        ('group:1', 'ai_metadata', str(img), 'NovelAI'),
        ('group:1', 'ai_metadata', str(img), 'NovelAI'),
        ('group:1', 'ai_metadata', str(img), 'NovelAI'),
    ])
    counts = build_view(tmp_path)
    assert counts.get('01_AI元数据_NovelAI') == 1
    cat = tmp_path / 'data' / 'view' / '01_AI元数据_NovelAI'
    files = [p.name for p in cat.rglob('*')
             if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}]
    assert len(files) == 1
    assert '_x3' in files[0]


def test_different_content_all_shown(tmp_path):
    """不同内容不受去重影响。"""
    from qq_onebot_whitelist.build_image_view import build_view

    img1 = make_image(tmp_path / 'a.png')
    img2 = make_image(tmp_path / 'b.png')
    make_db(tmp_path, [
        ('group:1', 'ai_metadata', str(img1), 'NovelAI'),
        ('group:1', 'ai_metadata', str(img2), 'NovelAI'),
    ])
    counts = build_view(tmp_path)
    assert counts.get('01_AI元数据_NovelAI') == 2


def test_dedup_keeps_newest_record(tmp_path):
    """重复内容保留最新记录（id 最大）作代表。"""
    from qq_onebot_whitelist.build_image_view import build_view

    img = make_image(tmp_path / 'a.png')
    make_db(tmp_path, [
        ('group:1', 'ai_metadata', str(img), 'NovelAI'),
        ('group:1', 'ai_metadata', str(img), 'NovelAI'),
    ])
    build_view(tmp_path)
    cat = tmp_path / 'data' / 'view' / '01_AI元数据_NovelAI'
    files = [p.name for p in cat.rglob('*')
             if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}]
    assert any('#2_' in f for f in files), files  # id=2 是最新的
    assert not any('#1_' in f for f in files)


def test_reclass_historical_parameters_to_a1111(tmp_path):
    """重判：parameters 键 → A1111；Software 键 → NovelAI。"""
    import json
    from unittest.mock import patch

    from qq_onebot_whitelist.image_meta import ImageMetadata
    from qq_onebot_whitelist.reclass_historical import reclass_historical

    webui = make_image(tmp_path / 'webui.png')
    nai = make_image(tmp_path / 'nai.png')
    make_db(tmp_path, [
        ('group:1', 'ai_metadata', str(webui), 'NovelAI'),
        ('group:1', 'ai_metadata', str(nai), 'NovelAI'),
    ])

    def fake_parse(path):
        if 'webui' in str(path):
            m = ImageMetadata(format='PNG')
            m.metadata_keys = ['parameters']
            m.has_ai_metadata, m.ai_source = True, 'A1111'
            return m
        m = ImageMetadata(format='PNG')
        m.metadata_keys = ['Title', 'Description', 'Software', 'Source', 'Comment']
        m.has_ai_metadata, m.ai_source = True, 'NovelAI'
        return m

    with patch('qq_onebot_whitelist.reclass_historical.parse_image_metadata', fake_parse):
        result = reclass_historical(tmp_path / 'data' / 'bot.db', dry_run=False)

    assert result['changed: NovelAI -> A1111'] == 1
    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    rows = dict(conn.execute('SELECT kept_path, ai_source FROM images').fetchall())
    conn.close()
    assert rows[str(webui)] == 'A1111'
    assert rows[str(nai)] == 'NovelAI'


def test_reclass_stego_verified_wins_over_text(tmp_path):
    """隐写 verified 时来源按载荷强证据算：无强证据不再硬标 NovelAI。"""
    from unittest.mock import patch

    from qq_onebot_whitelist.image_meta import ImageMetadata
    from qq_onebot_whitelist.reclass_historical import reclass_historical

    img = make_image(tmp_path / 'stego.png')
    make_db(tmp_path, [('group:1', 'ai_metadata', str(img), '')])

    def fake_parse(path):
        m = ImageMetadata(format='PNG')
        m.metadata_keys = ['parameters']
        # 载荷文本没有强证据（classify 只给 suspect/None）：重判不得硬标 NovelAI
        m.has_ai_metadata, m.ai_source = True, 'suspect:NovelAI'
        m.stego_state, m.stego_excerpt = 'verified', '{"prompt":"x"}'
        return m

    with patch('qq_onebot_whitelist.reclass_historical.parse_image_metadata', fake_parse):
        result = reclass_historical(tmp_path / 'data' / 'bot.db', dry_run=False)

    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    src = conn.execute('SELECT ai_source FROM images').fetchone()[0]
    conn.close()
    assert src == ''  # 验证不出工具 → 保留未知


def test_reclass_stego_payload_strong_evidence_decides(tmp_path):
    """隐写载荷有强证据（如 A1111 参数块）时按载荷来源重判。"""
    from unittest.mock import patch

    from qq_onebot_whitelist.image_meta import ImageMetadata
    from qq_onebot_whitelist.reclass_historical import reclass_historical

    img = make_image(tmp_path / 'stego-params.png')
    make_db(tmp_path, [('group:1', 'ai_metadata', str(img), 'NovelAI')])

    def fake_parse(path):
        m = ImageMetadata(format='PNG')
        m.metadata_keys = ['stealth_pnginfo']
        # 新版 parse：载荷是普通参数块 → A1111（不再因容器判 NovelAI）
        m.has_ai_metadata, m.ai_source = True, 'A1111'
        m.stego_state, m.stego_excerpt = 'verified', '1girl\nNegative prompt: blurry'
        return m

    with patch('qq_onebot_whitelist.reclass_historical.parse_image_metadata', fake_parse):
        result = reclass_historical(tmp_path / 'data' / 'bot.db', dry_run=False)

    assert result['changed: NovelAI -> A1111'] == 1
    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    src = conn.execute('SELECT ai_source FROM images').fetchone()[0]
    conn.close()
    assert src == 'A1111'

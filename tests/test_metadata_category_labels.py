"""未知 AI 来源的报告分类与增量图库覆盖。"""

import sqlite3

from PIL import Image


def _make_project_db(project_dir):
    data = project_dir / 'data'
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
    conn.commit()
    conn.close()


def _image(path, color):
    Image.new('RGB', (24, 18), color).save(path, 'PNG')
    return path


def test_home_image_total_uses_merged_gallery_count_once(tmp_path):
    from qq_onebot_whitelist.build_image_view import ALL_GALLERY_DIR, write_view_index

    view = tmp_path / 'view'
    for name in (ALL_GALLERY_DIR, '01_AI元数据_ComfyUI', '02_群友好评'):
        (view / name).mkdir(parents=True)
    write_view_index(view, {ALL_GALLERY_DIR: 4, '01_AI元数据_ComfyUI': 3, '02_群友好评': 1})

    index = (view / 'index.html').read_text(encoding='utf-8')
    assert '图片 <b>4</b> 张' in index
    assert '分类 <b>2</b> 个' in index


def _insert_image(project_dir, *, path, reason, source=None, sha, context_reason=None, seen_at='2026-10-01 10:00:00'):
    conn = sqlite3.connect(project_dir / 'data' / 'bot.db')
    conn.execute(
        "INSERT INTO images (scope, user_id, seen_at, format, width, height, size, has_ai_metadata, "
        "ai_source, retention_reason, kept_path, sha256, context_reason) "
        "VALUES ('group:test', 'test-user', ?, 'PNG', 24, 18, ?, 1, ?, ?, ?, ?, ?)",
        (seen_at, path.stat().st_size, source, reason, str(path), sha, context_reason),
    )
    conn.commit()
    conn.close()


def test_export_unknown_metadata_source_categories_match_report(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset, row_category

    paths = [
        _image(tmp_path / 'unknown-null.png', (40, 10, 10)),
        _image(tmp_path / 'unknown-blank.png', (10, 40, 10)),
        _image(tmp_path / 'a1111.png', (10, 10, 40)),
    ]
    # 导出模块的行分类应与报告 helper 使用同一映射。
    from qq_onebot_whitelist.build_image_view import image_category

    for value in (None, '', '   '):
        row = {'retention_reason': 'ai_metadata', 'ai_source': value, 'saved_category': ''}
        assert row_category(row) == image_category('ai_metadata', value) == '01_AI元数据_来源未识别'
    assert row_category({'retention_reason': 'ai_metadata', 'ai_source': 'A1111'}) == (
        image_category('ai_metadata', 'A1111')
    ) == '01_AI元数据_StableDiffusion_WebUI'

    _make_project_db(tmp_path)
    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    for path, source, sha in zip(paths, (None, '   ', 'A1111'),
                                 ('unknown-null', 'unknown-blank', 'a1111')):
        conn.execute(
            "INSERT INTO images (scope, user_id, seen_at, format, width, height, size, has_ai_metadata, "
            "ai_source, retention_reason, kept_path, sha256) "
            "VALUES ('group:test', 'test-user', '2026-10-01 10:00:00', 'PNG', 24, 18, ?, 1, ?, 'ai_metadata', ?, ?)",
            (path.stat().st_size, source, str(path), sha),
        )
    conn.commit()
    conn.close()
    stats = export_dataset(tmp_path, categories=['01_AI元数据_来源未识别'], dry_run=True)
    assert stats['manifest']['counts']['selected'] == 2
    assert stats['manifest']['by_category'] == {'01_AI元数据_来源未识别': 2}


def test_unknown_metadata_main_and_context_share_category_without_quality_claim(tmp_path):
    from qq_onebot_whitelist.build_image_view import build_view

    _make_project_db(tmp_path)
    main = _image(tmp_path / 'main.png', (80, 20, 20))
    context = _image(tmp_path / 'context.png', (20, 80, 20))
    _insert_image(tmp_path, path=main, reason='ai_metadata', source=None, sha='unknown-main')
    _insert_image(tmp_path, path=context, reason='xiaofanqie_obfuscated', source='  ',
                  sha='unknown-context', context_reason='ai_metadata')

    counts = build_view(tmp_path)
    category = tmp_path / 'data' / 'view' / '01_AI元数据_来源未识别'
    assert counts['01_AI元数据_来源未识别'] == 2
    chunk_text = '\n'.join(p.read_text(encoding='utf-8') for p in (category / 'chunks').glob('chunk-*.js'))
    assert 'unknown-main' not in chunk_text  # hashes stay database-only
    assert '%231_24x18_ai_metadata.png' in chunk_text
    assert '%232_24x18_xiaofanqie_obfuscated.png' in chunk_text
    index = (tmp_path / 'data' / 'view' / 'index.html').read_text(encoding='utf-8')
    assert '01_AI元数据_来源未识别' in index
    assert '可信度最高' not in index
    assert '不是所有元数据图片的总数' in index


def test_new_candidate_is_added_to_all_gallery_sort_chunks_on_rebuild(tmp_path):
    from qq_onebot_whitelist.build_image_view import ALL_GALLERY_DIR, build_view

    _make_project_db(tmp_path)
    first = _image(tmp_path / 'first.png', (80, 20, 20))
    _insert_image(tmp_path, path=first, reason='positive_feedback', source=None, sha='first')
    build_view(tmp_path)

    candidate = _image(tmp_path / 'candidate.png', (20, 80, 20))
    _insert_image(tmp_path, path=candidate, reason='candidate', source=None, sha='candidate',
                  seen_at='2026-10-02 10:00:00')
    counts = build_view(tmp_path)

    assert counts['04_候选待观察'] == 1
    assert counts[ALL_GALLERY_DIR] == 2
    candidate_dir = tmp_path / 'data' / 'view' / '04_候选待观察'
    assert len(list(candidate_dir.rglob('*.png'))) == 1
    all_dir = tmp_path / 'data' / 'view' / ALL_GALLERY_DIR
    for subdir in ('chunks', 'chunks-size', 'chunks-name', 'chunks-res'):
        files = list((all_dir / subdir).glob('chunk-*.js'))
        assert files, subdir
        payloads = '\n'.join(p.read_text(encoding='utf-8') for p in files)
        assert '%232_24x18_candidate.png' in payloads, subdir
        assert '04_候选待观察' in payloads, subdir
    # 分组选择器也列出候选分类，便于从总览页筛选。
    all_index = (all_dir / 'index.html').read_text(encoding='utf-8')
    assert '04_候选待观察（1张）' in all_index
    assert 'id="candidateQuick"' in all_index and '待观察 1 张' in all_index


def test_changed_metadata_category_refreshes_existing_all_page_info(tmp_path):
    import json
    from qq_onebot_whitelist.build_image_view import ALL_GALLERY_DIR, UNKNOWN_AI_CATEGORY, build_view

    _make_project_db(tmp_path)
    original = _image(tmp_path / 'source.png', (80, 20, 20))
    _insert_image(tmp_path, path=original, reason='ai_metadata', source='A1111', sha='metadata')
    build_view(tmp_path)
    with sqlite3.connect(tmp_path / 'data' / 'bot.db') as conn:
        conn.execute('UPDATE images SET ai_source=NULL')
    build_view(tmp_path)
    text = (tmp_path / 'data' / 'view' / ALL_GALLERY_DIR / 'info' / '1.js').read_text(encoding='utf-8')
    info = json.loads(text[text.index('{'):text.rindex('}')+1])
    assert info['c'] == UNKNOWN_AI_CATEGORY

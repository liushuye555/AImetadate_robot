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
    # 共享样式骨架：viewport 与统计 chips
    assert 'name="viewport"' in html
    assert '图片 <b>6</b> 张' in html


def test_write_view_index_renders_link_and_file_totals(tmp_path):
    view = tmp_path / 'view'
    view.mkdir(parents=True)

    write_view_index(view, {'resource_links': 12, 'resource_files': 3})

    html = (view / 'index.html').read_text(encoding='utf-8')
    assert '链接 <b>12</b> 条' in html
    assert '文件 <b>3</b> 个' in html
    assert '图片 <b>0</b> 张' in html


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
    files = [p.name for p in cat.rglob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}]
    assert len(files) == 1
    assert "_还原" in files[0]
    assert "解混淆" not in files[0]
    index = (tmp_path / "data" / "view" / "index.html").read_text(encoding="utf-8")
    assert "遮罩混淆还原图" in index
    gallery = (cat / "index.html").read_text(encoding="utf-8")
    assert "maskRestored" in gallery
    assert "blur" in gallery
    masked_chunks = "\n".join(p.read_text(encoding="utf-8") for p in cat.rglob("chunk-*.js"))
    assert '"masked":true' in masked_chunks


def test_build_view_batch_folds_12_but_not_31(tmp_path):
    import sqlite3

    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / "data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / "bot.db")
    conn.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
        sha256 TEXT, ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
        deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, bound_prompt TEXT, prompt_key TEXT,
        context_reason TEXT, raw_json TEXT)""")
    conn.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)""")
    conn.execute("""CREATE TABLE ai_context_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, scope TEXT,
        start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT)""")
    img = tmp_path / "img.png"
    img.write_bytes(b"x" * 10)
    for i in range(12):
        conn.execute(
            "INSERT INTO images (scope, user_id, seen_at, format, width, height, ai_source, retention_reason, kept_path, prompt_key) "
            "VALUES ('group:1','u',?,'PNG',64,64,'ComfyUI','ai_metadata',?,'11111111')",
            (f"2026-08-01 {10 + i // 60:02d}:{i % 60:02d}:00", str(img)),
        )
    for i in range(31):
        conn.execute(
            "INSERT INTO images (scope, user_id, seen_at, format, width, height, ai_source, retention_reason, kept_path, prompt_key) "
            "VALUES ('group:1','u',?,'PNG',64,64,'ComfyUI','ai_metadata',?,'22222222')",
            (f"2026-08-02 {10 + i // 60:02d}:{i % 60:02d}:00", str(img)),
        )
    conn.commit()
    conn.close()

    build_view(tmp_path)
    files = [p.name for p in (tmp_path / "data" / "view" / "01_AI元数据_ComfyUI").rglob("*.png")]
    assert any("_pk11111111" in f for f in files)   # 12 张同一工作流 → 折叠
    assert not any("_pk22222222" in f for f in files)  # 31 张超上限 → 不折


def test_view_prompt_bound_card_and_batch_collapse(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.build_image_view import build_view
    data = tmp_path / "data"
    data.mkdir(parents=True)
    store = __import__("qq_onebot_whitelist.store", fromlist=["Store"]).Store(data / "bot.db")
    img = data / "images" / "ai" / "ab" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x" * 10)
    img2 = data / "images" / "ai" / "ab" / "b.png"
    img2.write_bytes(b"y" * 10)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "a", "format": "PNG", "size": 10, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "prompt_bound", "bound_prompt": "1girl, solo",
    }, raw={})
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "b", "format": "PNG", "size": 10, "width": 64, "height": 64,
        "kept_path": str(img2), "retention_reason": "ai_metadata", "ai_source": "ComfyUI",
        "text_excerpt": "1girl, solo", "prompt_key": "samekey",
    }, raw={})
    counts = build_view(tmp_path)
    bind_dir = tmp_path / "data" / "view" / "03_提示词绑定"
    page = next(bind_dir.rglob("index.html"))
    html = page.read_text(encoding="utf-8")
    context_chunks = "\n".join(p.read_text(encoding="utf-8") for p in bind_dir.rglob("chunk-*.js"))
    assert "1girl, solo" in context_chunks
    ai_dir = tmp_path / "data" / "view" / "01_AI元数据_ComfyUI"
    html2 = next(ai_dir.rglob("index.html")).read_text(encoding="utf-8")
    ai_chunks = "\n".join(p.read_text(encoding="utf-8") for p in ai_dir.rglob("chunk-*.js"))
    assert "IntersectionObserver" in html2
    assert "window.__galleryAcceptChunk" in ai_chunks
    index = (tmp_path / "data" / "view" / "index.html").read_text(encoding="utf-8")
    # 分组改为徽标弹出的组内视图：入口页不再有"同批折叠"开关
    assert "collapseBatches" not in index
    assert "遮罩混淆还原图" in index


def test_view_prompt_bound_page_masks_deobfuscated(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.build_image_view import build_view
    data = tmp_path / "data"
    data.mkdir(parents=True)
    store = __import__("qq_onebot_whitelist.store", fromlist=["Store"]).Store(data / "bot.db")
    img = data / "images" / "ai" / "ab" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x" * 10)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "a", "format": "PNG", "size": 10, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "prompt_bound",
        "bound_prompt": "1girl, solo", "deobfuscated": True,
    }, raw={})
    build_view(tmp_path)
    page = (tmp_path / "data" / "view" / "03_提示词绑定" / "index.html").read_text(encoding="utf-8")
    chunks = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "data" / "view" / "03_提示词绑定").rglob("chunk-*.js"))
    assert '"masked":true' in chunks
    assert "maskRestored" in page


def test_relink_view_copy_replaces_copy_with_hardlink(tmp_path):
    import os
    import shutil

    from qq_onebot_whitelist.build_image_view import relink_view_copy

    src = tmp_path / "src.png"
    src.write_bytes(b"x" * 10)
    dst = tmp_path / "dst.png"
    shutil.copy2(src, dst)
    assert not os.path.samefile(src, dst)

    assert relink_view_copy(src, dst)
    assert os.path.samefile(src, dst)


def test_build_view_relinks_copy_fallbacks(tmp_path, monkeypatch):
    import os
    import shutil
    import sqlite3

    from qq_onebot_whitelist import build_image_view as module
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
        "INSERT INTO images (scope, user_id, format, width, height, retention_reason, kept_path) "
        "VALUES ('group:1', 'u', 'PNG', 64, 64, 'ai_metadata', ?)",
        (str(img),),
    )
    conn.commit()
    conn.close()

    original = module.make_link_or_copy

    def force_copy(src, dst):
        mode = original(src, dst)
        if mode == "hardlink":
            dst.unlink()
            shutil.copy2(src, dst)
            return "copy"
        return mode

    monkeypatch.setattr(module, "make_link_or_copy", force_copy)
    build_view(tmp_path)

    view_file = next((tmp_path / "data" / "view").rglob("*.png"))
    assert os.path.samefile(img, view_file)


def test_category_gallery_uses_complete_image_thumbnails(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '竖图'
    category.mkdir()
    (category / '#1_2512x3768_ai_metadata.png').write_bytes(b'not-decoded-by-gallery')

    write_category_gallery(category)

    page = (category / 'index.html').read_text(encoding='utf-8')
    assert 'object-fit:contain' in page
    assert 'object-fit:cover' not in page
    assert 'object-fit:contain' in page


def test_category_gallery_restores_uniform_layout_and_expansion_reflow(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '01_AI元数据_ComfyUI'
    category.mkdir()
    (category / '#2_64x64_ai_metadata_pk12345678.png').write_bytes(b'x')
    (category / '#1_64x64_ai_metadata_pk12345678.png').write_bytes(b'x')

    write_category_gallery(category)

    page = (category / 'index.html').read_text(encoding='utf-8')
    assert '.gallery-item' in page
    assert 'group.cards' in page
    # 组缩略图浮层：点徽标浮出组员缩略图（groupOverlay），点图看大图，点空白返回
    assert 'insertBefore' not in page
    assert '__galleryGroup' in page
    assert 'overlayHint' in page
    assert 'groupOverlay' in page
    assert 'groupHint' in page
    assert 'object-fit:contain' in page
    assert '.broken-image' in page
    assert 'function isPreviewVisible' in page
    assert 'async function showAdjacent' in page
    assert "if(isPreviewVisible(anchor))" in page
    chunk = (category / 'chunks' / 'chunk-0001.js').read_text(encoding='utf-8')
    assert '"batch":"12345678","batch_total":2' in chunk
    group_files = list((category / 'groups').glob('12345678.js'))
    assert len(group_files) == 1
    assert '"kind":"同批"' in group_files[0].read_text(encoding='utf-8')


def test_category_gallery_loads_images_from_local_chunks_on_demand(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '01_AI元数据_ComfyUI'
    category.mkdir()
    for image_id in range(1, 126):
        (category / f'#{image_id}_64x64_ai_metadata.png').write_bytes(b'x')

    write_category_gallery(category)

    page = (category / 'index.html').read_text(encoding='utf-8')
    chunks = sorted((category / 'chunks').glob('chunk-*.js'))
    assert len(chunks) == 2
    assert 'IntersectionObserver' in page
    assert 'window.__galleryAcceptChunk' in page
    chunk_text = '\n'.join(chunk.read_text(encoding='utf-8') for chunk in chunks)
    assert "image.loading='lazy'" in page
    assert "image.decoding='async'" in page
    assert 'grid.addEventListener' in page
    assert '%231_' not in page
    assert '%23125_64x64_ai_metadata.png' in chunks[0].read_text(encoding='utf-8')
    assert '%231_64x64_ai_metadata.png' in chunks[1].read_text(encoding='utf-8')



def test_write_view_index_ignores_generated_chunk_files_in_image_count(tmp_path):
    view = tmp_path / 'view'
    category = view / '06_聊天记录收藏' / '未分类'
    category.mkdir(parents=True)
    (category / '#1_64x64_chat_record_saved.png').write_bytes(b'x')
    (category / 'chunks').mkdir()
    (category / 'chunks' / 'chunk-0001.js').write_text('window.__galleryAcceptChunk(0,[])', encoding='utf-8')

    write_view_index(view, {})

    html = (view / 'index.html').read_text(encoding='utf-8')
    assert '06_%E8%81%8A%E5%A4%A9%E8%AE%B0%E5%BD%95%E6%94%B6%E8%97%8F/' in html
    assert '1 张' in html


def test_context_gallery_uses_incremental_chunks_too(tmp_path):
    from qq_onebot_whitelist.build_image_view import _write_context_gallery

    category = tmp_path / '03_提示词绑定'
    items = [
        {
            'id': str(i),
            'image_rel': f'img/{i}.png',
            'meta': '2026-09-05 · 64x64',
            'text': f'prompt-{i}',
            'deobfuscated': i == 1,
        }
        for i in range(1, 126)
    ]

    _write_context_gallery(category, items, '03 提示词绑定')

    page = (category / 'index.html').read_text(encoding='utf-8')
    chunks = sorted((category / 'chunks').glob('chunk-*.js'))
    assert len(chunks) == 2
    assert 'context-grid' in page
    assert 'prompt-125' not in page
    assert 'prompt-125' in chunks[1].read_text(encoding='utf-8')


def test_category_gallery_embeds_image_ratio_for_aspect_fit(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '01_AI元数据_ComfyUI'
    category.mkdir()
    (category / '#1_1920x1080_ai_metadata.png').write_bytes(b'x')
    (category / '#2_800x1200_ai_metadata.png').write_bytes(b'x')

    write_category_gallery(category)

    page = (category / 'index.html').read_text(encoding='utf-8')
    # CSS 默认比例 + JS 按图片真实宽高覆盖
    assert 'aspect-ratio:4/3' in page
    assert 'anchor.style.aspectRatio' in page
    chunks = '\n'.join(p.read_text(encoding='utf-8') for p in category.rglob('chunk-*.js'))
    assert '"w":1920' in chunks and '"h":1080' in chunks
    assert '"w":800' in chunks and '"h":1200' in chunks


def test_category_gallery_generates_cached_thumbnails(tmp_path):
    import io

    from PIL import Image

    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '01_AI元数据_ComfyUI'
    category.mkdir()
    img = Image.new('RGB', (400, 200), (30, 60, 120))
    img.save(category / '#1_400x200_ai_metadata.png')

    write_category_gallery(category, project_dir=tmp_path)

    thumb = tmp_path / 'data' / 'view-thumbs' / '01_AI元数据_ComfyUI' / '#1_400x200_ai_metadata.jpg'
    assert thumb.exists()
    with Image.open(thumb) as small:
        assert max(small.size) <= 640
    chunks = '\n'.join(p.read_text(encoding='utf-8') for p in category.rglob('chunk-*.js'))
    assert '"thumb":"../../view-thumbs/' in chunks
    # 卡片加载小图，原图仍在 anchor.href 上供放大查看
    page = (category / 'index.html').read_text(encoding='utf-8')
    assert "item.thumb||item.href" in page


def test_background_css_and_wallpaper_helpers(tmp_path):
    from qq_onebot_whitelist.view_theme import background_css, find_wallpaper, page_shell

    assert background_css(None) == ''
    assert background_css('wallpaper.jpg').count('url("wallpaper.jpg")') == 1
    assert 'url("../wallpaper.png")' in background_css('../wallpaper.png')

    (tmp_path / 'wallpaper.jpg').write_bytes(b'x')
    assert find_wallpaper(tmp_path) == 'wallpaper.jpg'
    assert find_wallpaper(tmp_path.parent) is None

    html = page_shell(title='t', body='b', background=background_css('wallpaper.jpg'))
    # 壁纸挂在 wallpaper-ready 类上，由空闲回调延迟挂载，不阻塞首屏
    assert 'body.wallpaper-ready' in html
    assert 'wallpaper-ready")' in html


def test_view_pages_embed_theme_toggle_and_light_palette(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_view_index

    view = tmp_path / 'view'
    view.mkdir(parents=True)
    write_view_index(view, {})

    html = (view / 'index.html').read_text(encoding='utf-8')
    # head 内早期初始化（跟随系统/记忆），右上角固定切换按钮，浅色变量表
    assert 'localStorage.getItem("viewTheme")' in html
    assert 'prefers-color-scheme' in html
    assert 'id="themeToggle"' in html
    assert 'html[data-theme="light"]' in html
    assert '--bg:#f2f4f8' in html


def test_gallery_page_embeds_theme_toggle_and_light_palette(tmp_path):
    from qq_onebot_whitelist.build_image_view import write_category_gallery

    category = tmp_path / '01_AI元数据_ComfyUI'
    category.mkdir()
    (category / '#1_64x64_ai_metadata.png').write_bytes(b'x')

    write_category_gallery(category)

    page = (category / 'index.html').read_text(encoding='utf-8')
    assert 'localStorage.getItem("viewTheme")' in page
    assert 'id="themeToggle"' in page
    assert 'html[data-theme="light"]' in page


def test_gallery_embeds_user_filter_with_nickname(tmp_path):
    """uid 进 chunk、用户下拉带昵称与数量；无名可查时退回 uid。"""
    import sqlite3

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
    img1 = tmp_path / "img1.png"
    img1.write_bytes(b"x" * 10)
    img2 = tmp_path / "img2.png"
    img2.write_bytes(b"y" * 10)
    conn.execute(
        "INSERT INTO images (scope, user_id, seen_at, format, width, height, retention_reason, kept_path, text_excerpt) "
        "VALUES ('group:1', '100', '2026-09-24 10:00:00', 'PNG', 64, 64, 'positive_feedback', ?, 'shiroko beach')",
        (str(img1),))
    conn.execute(
        "INSERT INTO images (scope, user_id, seen_at, format, width, height, retention_reason, kept_path, text_excerpt) "
        "VALUES ('group:1', '200', '2026-08-01 10:00:00', 'PNG', 64, 64, 'positive_feedback', ?, '')",
        (str(img2),))
    conn.execute(
        "INSERT INTO messages (scope, user_id, raw_json) VALUES ('group:1', '100', ?)",
        ('{"sender":{"card":"阿熊","nickname":"bear"}}',))
    conn.commit()
    conn.close()

    build_view(tmp_path)
    cat = tmp_path / "data" / "view" / "02_群友好评"
    page = (cat / "index.html").read_text(encoding="utf-8")
    assert 'id="userSel"' in page
    assert '阿熊（100 · 1张）' in page
    assert '200 · 1张' in page  # 无昵称消息可查时退回 uid
    chunk = (cat / "chunks" / "chunk-0001.js").read_text(encoding="utf-8")
    assert '"uid":"100"' in chunk and '"uid":"200"' in chunk
    # 日期/关键词进 chunk，页面有完整筛选控件和月份下拉、分辨率排序分块
    assert '"ts":"2026-09-24"' in chunk
    assert '"kw":"shiroko beach"' in chunk
    assert '2026-09（1张）' in page and '2026-08（1张）' in page
    for marker in ('id="sizeSel"', 'id="resSel"', 'id="monthSel"', 'id="searchBox"',
                   'id="dupOnly"', 'id="thumbSel"', 'chunks-res'):
        assert marker in page, marker
    assert (cat / "chunks-res" / "chunk-0001.js").exists()


def test_saved_collection_index_links_single_encoded(tmp_path):
    """06 收藏入口页的子分类链接只编码一次（中文分类名二次编码会坏链）。"""
    import sqlite3

    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / "data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / "bot.db")
    conn.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
        ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
        deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT, sha256 TEXT,
        saved_category TEXT)""")
    conn.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)""")
    conn.execute("""CREATE TABLE ai_context_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, scope TEXT,
        start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT)""")
    img = tmp_path / "saved.png"
    img.write_bytes(b"x" * 10)
    conn.execute(
        "INSERT INTO images (scope, user_id, format, width, height, retention_reason, kept_path, saved_category) "
        "VALUES ('group:1', 'u', 'PNG', 64, 64, 'chat_record_saved', ?, '二次元')", (str(img),))
    conn.commit()
    conn.close()

    build_view(tmp_path)
    index = (tmp_path / "data" / "view" / "06_聊天记录收藏" / "index.html").read_text(encoding="utf-8")
    assert "%25" not in index
    assert "href=\"%E4%BA%8C%E6%AC%A1%E5%85%83/index.html\"" in index
    assert (tmp_path / "data" / "view" / "06_聊天记录收藏" / "二次元" / "index.html").exists()

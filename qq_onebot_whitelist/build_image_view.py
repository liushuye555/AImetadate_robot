from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import html
import json
import os
import random
import re
import shutil
import sqlite3
import time
from urllib.parse import quote

from .view_theme import THEME_INIT_JS, THEME_TOGGLE_HTML, THEME_TOGGLE_JS, THEME_VARS_CSS

CATEGORY_NAMES = {
    'ai_metadata': '01_AI元数据',
    'positive_feedback': '02_群友好评',
    'prompt_bound': '03_提示词绑定',
    'params_discussion': '03_参数讨论',
    'candidate': '04_候选待观察',
    'xiaofanqie_obfuscated': '05_小番茄混淆',
    'xiaofanqie_compressed': '05_小番茄混淆_压缩',
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

def stale_view_counts(view: Path) -> dict[str, int]:
    """不重建视图，直接从现有视图目录统计各分类图片数（低开销，供负载忙时兜底）。"""
    image_exts = IMAGE_EXTENSIONS
    counts: dict[str, int] = {}
    if view.exists():
        for cat in sorted(view.iterdir()):
            if cat.is_dir():
                n = sum(1 for f in cat.rglob('*') if f.is_file() and f.suffix.lower() in image_exts)
                if n:
                    counts[cat.name] = n
    return counts


def safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', text)[:180]


def source_path(base: Path, kept_path: str) -> Path:
    p = Path(kept_path)
    if not p.is_absolute():
        p = base / p
    return p


def url_path(path: str) -> str:
    return '/'.join(quote(part) for part in path.replace('\\\\', '/').replace('\\', '/').split('/'))


def group_name_map_from_conn(conn: sqlite3.Connection) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        rows = conn.execute("SELECT scope, raw_json FROM messages WHERE scope LIKE 'group:%' ORDER BY id DESC").fetchall()
    except sqlite3.OperationalError:
        return names
    for row in rows:
        scope = str(row['scope'] if isinstance(row, sqlite3.Row) else row[0])
        raw_json = row['raw_json'] if isinstance(row, sqlite3.Row) else row[1]
        group_id = scope.split(':', 1)[1] if ':' in scope else scope
        if group_id in names:
            continue
        try:
            import json
            raw = json.loads(raw_json or '{}')
        except Exception:
            raw = {}
        name = str(raw.get('group_name') or '').strip()
        if name:
            names[group_id] = name
            names[scope] = name
    return names


CATEGORY_ICONS = {'01': '🎨', '02': '⭐', '03': '🧩', '04': '👀', '05': '🍅', '06': '📌'}
CATEGORY_DESC = {
    '01': '自带 ComfyUI/NovelAI 等生成元数据，可信度最高',
    '02': '被引用、好评或求提示词后晋升',
    '03': '图片与提示词/参数成对出现',
    '04': '暂存候选，等待后续反馈',
    '05': 'Gilbert 曲线验证的混淆还原图片',
    '06': '聊天记录中显式保存的图片',
}


def _index_card(href: str, icon: str, title: str, desc: str, count: str) -> str:
    count_html = f'<div class="count">{html.escape(count)}</div>' if count else ''
    return (
        f'<a class="card" href="{html.escape(url_path(href))}">'
        f'<h2><span class="icon">{icon}</span>{html.escape(title)}</h2>'
        f'<p class="muted">{html.escape(desc)}</p>{count_html}</a>'
    )


def _write_if_changed(path: Path, content: str) -> bool:
    """内容没变就不动文件：减少无谓的磁盘写入（索引/资源页每轮都在重建）。"""
    try:
        if path.exists() and path.read_text(encoding='utf-8') == content:
            return False
    except OSError:
        pass
    path.write_text(content, encoding='utf-8')
    return True


def _make_wallpaper(project_dir: Path, view: Path, conn: sqlite3.Connection) -> str | None:
    """随机挑一张横版高清归档图硬链进视图目录，作为全屏壁纸背景。

    只在 ai_metadata/positive_feedback 里选（质量信号最强），尺寸/比例
    适合铺满屏幕；挑不出就返回 None，页面回退到纯渐变背景。
    壁纸每天换一张：同一天内跳过 PIL 重压缩与重写（每小时同步都不再写盘）。
    """
    dst = view / 'wallpaper.jpg'
    stamp = view / '.wallpaper-day'
    today = time.strftime('%Y-%m-%d')
    if dst.exists() and stamp.exists():
        try:
            if stamp.read_text().strip() == today:
                return None  # 当天已生成，跳过（不打印，避免每轮刷日志）
        except OSError:
            pass
    try:
        rows = conn.execute(
            "SELECT kept_path FROM images "
            "WHERE kept_path IS NOT NULL AND width >= 1200 AND height >= 700 "
            "AND width * 1.0 / height BETWEEN 1.0 AND 2.4 "
            "AND retention_reason IN ('ai_metadata', 'positive_feedback') "
            "ORDER BY id DESC LIMIT 80"
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    candidates = []
    for row in rows:
        src = source_path(project_dir, row['kept_path'])
        if src.exists() and src.suffix.lower() in IMAGE_EXTENSIONS:
            candidates.append(src)
    if not candidates:
        return None
    src = random.choice(candidates)
    # 压成 1920px 内的 JPEG（几百 KB），首屏不再被几 MB 的原图卡住
    try:
        from PIL import Image
        with Image.open(src) as img:
            rgb = img.convert('RGB')
            rgb.thumbnail((WALLPAPER_MAX_DIM, WALLPAPER_MAX_DIM), Image.LANCZOS)
            rgb.save(dst, 'JPEG', quality=82)
        stamp.write_text(today, encoding='utf-8')
        return dst.name
    except Exception:
        pass
    dst = view / ('wallpaper' + src.suffix.lower())
    if make_link_or_copy(src, dst) == 'url':
        dst.with_suffix(dst.suffix + '.url').unlink(missing_ok=True)
        return None
    return dst.name


def write_view_index(view: Path, counts: dict[str, int]) -> None:
    from .view_theme import background_css, find_wallpaper, page_shell

    background = background_css(find_wallpaper(view))

    categories = sorted([p for p in view.iterdir() if p.is_dir()], key=lambda p: p.name) if view.exists() else []
    link_total = int(counts.get('resource_links') or 0)
    file_total = int(counts.get('resource_files') or 0)
    image_total = sum(int(v) for key, v in counts.items() if key not in ('resource_links', 'resource_files'))
    chips = (
        f'<span class="chip">图片 <b>{image_total}</b> 张</span>'
        f'<span class="chip">分类 <b>{len(categories)}</b> 个</span>'
    )
    if link_total:
        chips += f'<span class="chip">链接 <b>{link_total}</b> 条</span>'
    if file_total:
        chips += f'<span class="chip">文件 <b>{file_total}</b> 个</span>'

    cards = []
    fixed_pages = [
        ('resources.html', '🔗', '高价值资源链接', '已过滤低价值分享，按群分类去重',
         f'{link_total} 条' if link_total else ''),
        ('files.html', '📦', '高价值文件/工作流', '文件名、类型、大小；不展示长下载 URL',
         f'{file_total} 个' if file_total else ''),
    ]
    for href, icon, title, desc, count in fixed_pages:
        cards.append(_index_card(href, icon, title, desc, count))
    for cat_dir in categories:
        count = counts.get(cat_dir.name)
        if count is None:
            count = sum(1 for p in cat_dir.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
        prefix = cat_dir.name[:2]
        target = cat_dir.name + ('/index.html' if (cat_dir / 'index.html').exists() else '/')
        cards.append(_index_card(
            target,
            CATEGORY_ICONS.get(prefix, '🗂️'),
            cat_dir.name,
            CATEGORY_DESC.get(prefix, '图片分类视图'),
            f'{int(count)} 张',
        ))
    if not cards:
        cards.append('<article class="card"><h2>暂无图片分类</h2><p class="muted">等待维护脚本生成。</p></article>')

    mask_html = (
        '<div class="toggles">'
        '<label><input type="checkbox" id="maskRestored" checked> 遮罩混淆还原图（默认模糊，点击图片显示）</label>'
        '</div>'
        '<script>'
        'const maskBox=document.getElementById("maskRestored");'
        'try{maskBox.checked=localStorage.getItem("maskRestored")!=="0";}catch(e){}'
        'maskBox.addEventListener("change",()=>{try{localStorage.setItem("maskRestored",maskBox.checked?"1":"0");}catch(e){}});'
        '</script>'
    )
    body = (
        '<h1>图片与资源总览</h1>'
        '<p class="page-desc">分类视图入口；图库页面保持单页浏览，图片会随滚动按需加载，不会一次载入全部卡片。</p>'
        f'<div class="chips">{chips}</div>'
        + mask_html +
        f'<div class="grid">{"".join(cards)}</div>'
        '<p class="foot">视图由机器人从 data/bot.db 自动生成，可随时重建；原图以硬链接方式引用，不额外占用磁盘空间。</p>'
    )
    view.mkdir(parents=True, exist_ok=True)
    (view / 'index.html').write_text(
        page_shell(title='图片与资源总览', body=body, background=background),
        encoding='utf-8',
    )


def make_link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return 'exists'
    try:
        os.link(src, dst)
        return 'hardlink'
    except Exception:
        try:
            shutil.copy2(src, dst)
            return 'copy'
        except Exception:
            url = dst.with_suffix(dst.suffix + '.url')
            url.write_text('[InternetShortcut]\nURL=' + src.resolve().as_uri() + '\n', encoding='utf-8')
            return 'url'


def relink_view_copy(src: Path, dst: Path) -> bool:
    """把视图里的复制原子替换为指向归档原图的硬链接。"""
    tmp = dst.with_name(dst.name + '.hardlink')
    try:
        tmp.unlink(missing_ok=True)
        os.link(src, tmp)
        os.replace(tmp, dst)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def saved_category_name(value: object) -> str:
    value = safe_name(str(value or '').strip()).strip(' .')
    return value[:80] or '未分类'


def write_saved_collection_index(root: Path, categories: set[str]) -> None:
    """为聊天记录收藏根目录生成分类入口。"""
    from .view_theme import background_css, find_wallpaper, page_shell

    background = background_css(
        '../' + wp if (wp := find_wallpaper(root.parent)) else None
    )
    root.mkdir(parents=True, exist_ok=True)
    cards = []
    for category in sorted(categories):
        href = url_path(category + '/index.html')
        cards.append(_index_card(href, '🖼️', category, '按分类保存的聊天记录图片', ''))
    if not cards:
        cards.append('<article class="card"><h2>暂无聊天记录收藏</h2><p class="muted">回复合并聊天记录后发送 /保存图片。</p></article>')
    body = (
        '<nav class="crumbs"><a href="../index.html">← 返回总览</a></nav>'
        '<h1>聊天记录收藏</h1>'
        '<p class="page-desc">聊天记录中显式保存的图片，按分类独立展示；分类图库会随滚动按需加载。</p>'
        f'<div class="grid">{"".join(cards)}</div>'
        '<p class="foot">在回复合并聊天记录时发送 /保存图片，即可按填写分类归档其中的图片。</p>'
    )
    (root / 'index.html').write_text(
        page_shell(title='聊天记录收藏', body=body, background=background),
        encoding='utf-8',
    )


def _script_json(value: object) -> str:
    '''把数据安全地嵌入经典脚本，兼容本地 file:// 页面。'''
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


def _group_data_file(key: str) -> str:
    """组数据文件名：key 通常已是安全字符（dupNNNNN / pk 十六进制），异常时退哈希。"""
    safe = re.sub(r'[^a-z0-9_-]', '', key.lower())[:40]
    if not safe or safe != key.lower():
        return 'g' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]
    return safe


GALLERY_CHUNK_SIZE = 120

THUMBS_DIR = 'view-thumbs'
THUMB_MAX_DIM = 640
WALLPAPER_MAX_DIM = 1920


def _thumb_file(src: Path, dst: Path) -> bool:
    """生成（或按 mtime 复用）JPEG 缩略图；失败返回 False。"""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return True
        with Image.open(src) as img:
            rgb = img.convert('RGB')  # 兼容 RGBA/P/L，JPEG 无透明通道
            rgb.thumbnail((THUMB_MAX_DIM, THUMB_MAX_DIM), Image.LANCZOS)
            rgb.save(dst, 'JPEG', quality=82)
        return True
    except Exception:
        return False


def _gallery_batch_key(name: str) -> str:
    match = re.search(r'_pk([0-9a-f]{8})', name, re.IGNORECASE)
    return match.group(1).lower() if match else ''


def _dhash(path: Path) -> int:
    """64 位感知哈希（dhash）：对视觉相同/高度相似的图给出相近值。"""
    try:
        from PIL import Image
        with Image.open(path) as img:
            gray = img.convert('L').resize((9, 8), Image.LANCZOS)
        pixels = list(gray.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else 0)
        return bits
    except Exception:
        return 0


def _thumb_md5(path: Path) -> str:
    """缩略图字节 md5：像素完全相同的图缩略图逐字节一致，用作精确去重键。"""
    try:
        import hashlib
        h = hashlib.md5()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ''


def _assign_dup_groups(entries: list[tuple[str, int, tuple[int, int], str]]) -> dict[str, str]:
    """把视觉相同的图折叠成组（展示顺序传入）。

    entries: [(item_key, dhash, (w, h), thumb_md5)]，返回 key -> 组 id（仅含 >1 张的组）。
    同图必然同尺寸：按尺寸分桶，桶内先比缩略图 md5（像素完全相同的精确命中），
    再比 dhash 汉明距离 ≤6（重压缩/微裁剪等近似命中），避免全量两两比较。
    """
    reps_by_bucket: dict[tuple[int, int], list[tuple[int, str, str]]] = {}
    assign: dict[str, str] = {}
    group_seq = 0
    for key, digest, (width, height), md5 in entries:
        if not width or not height or (not digest and not md5):
            continue
        bucket = reps_by_bucket.setdefault((width, height), [])
        hit = None
        if md5:
            for rep in bucket:
                if rep[1] and rep[1] == md5:
                    hit = rep
                    break
        if hit is None and digest:
            for rep in bucket:
                if rep[0] and (rep[0] ^ digest).bit_count() <= 6:
                    hit = rep
                    break
        if hit is not None:
            assign[key] = hit[2]
            continue
        group_id = f'dup{group_seq:05d}'
        group_seq += 1
        bucket.append((digest, md5, group_id))
    counts: dict[str, int] = {}
    for group_id in assign.values():
        counts[group_id] = counts.get(group_id, 0) + 1
    return {key: group_id for key, group_id in assign.items() if counts[group_id] > 1}


def _write_gallery_chunks(cat_dir: Path, items: list[dict[str, object]], subdir: str = 'chunks') -> int:
    '''把图库元数据拆成按需加载的本地 JS 分块，不在入口页塞入全部图片。'''
    chunks_dir = cat_dir / subdir
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for old in chunks_dir.glob('chunk-*.js'):
        old.unlink(missing_ok=True)
    for start in range(0, len(items), GALLERY_CHUNK_SIZE):
        chunk_index = start // GALLERY_CHUNK_SIZE
        payload = _script_json(items[start:start + GALLERY_CHUNK_SIZE])
        (chunks_dir / f'chunk-{chunk_index + 1:04d}.js').write_text(
            f'window.__galleryAcceptChunk({chunk_index},{payload});\n',
            encoding='utf-8',
        )
    return (len(items) + GALLERY_CHUNK_SIZE - 1) // GALLERY_CHUNK_SIZE


_SORT_VIEWS: tuple[tuple[str, str], ...] = (
    ('chunks', '时间'),
    ('chunks-size', '大小'),
    ('chunks-name', '名称'),
)


def _write_gallery_chunk_sets(cat_dir: Path, items: list[dict[str, object]]) -> int:
    '''按多种排序各写一套 chunks（元数据小文件，图片本身共享），返回 chunk 数。'''
    by_size = sorted(items, key=lambda it: (-int(it.get('bytes') or 0), str(it.get('href') or '')))
    by_name = sorted(items, key=lambda it: str(it.get('href') or ''))
    _write_gallery_chunks(cat_dir, items, 'chunks')
    _write_gallery_chunks(cat_dir, by_size, 'chunks-size')
    _write_gallery_chunks(cat_dir, by_name, 'chunks-name')
    return (len(items) + GALLERY_CHUNK_SIZE - 1) // GALLERY_CHUNK_SIZE


def _gallery_page(
    *,
    title: str,
    count: int,
    chunk_count: int,
    context_mode: bool = False,
    background: str = '',
) -> str:
    '''生成单页图库壳；图片卡片由滚动/按钮触发的本地 chunk 按需追加。'''
    doc = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>__TITLE__</title>
<script>__THEME_INIT__</script>
<style>
__THEME_VARS__
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--text)}
__WALLPAPER_CSS__
/* 图库页专属：壁纸只作氛围，遮罩加深，图片区不与背景原图混叠 */
body.wallpaper-ready::before{background:linear-gradient(180deg,rgba(13,15,19,.82) 0%,rgba(13,15,19,.87) 50%,rgba(13,15,19,.95) 100%)}
html[data-theme="light"] body.wallpaper-ready::before{background:linear-gradient(180deg,rgba(242,244,248,.86) 0%,rgba(242,244,248,.9) 50%,rgba(242,244,248,.96) 100%)}
header{padding:18px 22px;position:sticky;top:0;background:var(--head-bg);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);z-index:2;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0 0 4px}.muted{color:var(--muted);font-size:13px}
#back{color:var(--accent-soft);text-decoration:none;font-size:13px;margin-right:14px}
.toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:6px 0 0;font-size:13px}
#jumpTo{width:74px;padding:4px 8px;border-radius:6px;border:1px solid var(--line-strong);background:var(--panel);color:var(--text)}
#topBtn,#loadMore{padding:4px 12px;border-radius:6px;border:1px solid var(--line-strong);background:var(--panel);color:var(--accent-soft);cursor:pointer}
#loadMore:disabled{opacity:.55;cursor:default}
select#sortSel{padding:4px 10px;border-radius:6px;border:1px solid var(--line-strong);background:var(--panel);color:var(--text);font-size:13px;cursor:pointer;outline:0}
select#sortSel:focus{border-color:var(--accent)}
select#sortSel option{background:var(--panel);color:var(--text)}
/* 图库网格：横向顺序（从左到右逐行排列），按图片高度自动跨行补齐，无空洞 */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;padding:16px 22px;grid-auto-rows:8px;align-items:start}
.grid.context-grid{grid-auto-rows:auto;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.gallery-item{position:relative;display:inline-block;width:100%;min-width:0;margin:0 0 8px;break-inside:avoid;-webkit-column-break-inside:avoid;border-radius:8px;overflow:hidden;background:var(--panel);border:1px solid var(--line)}
.context-card{position:relative;min-width:0;padding:10px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.cell{position:relative;display:block;width:100%;border-radius:8px;overflow:hidden;cursor:zoom-in;background:var(--img-bg)}
.context-card .cell{aspect-ratio:4/3;min-height:170px;max-height:420px}
.cell img{width:100%;height:auto;object-fit:contain;display:block;background:var(--img-bg)}
.context-card .cell img{height:100%;max-height:60vh}
.gallery-item[hidden]{display:none!important}.broken-image{display:flex;align-items:center;justify-content:center;width:100%;height:100%;padding:16px;box-sizing:border-box;color:var(--broken-fg);background:var(--broken-bg);font-size:12px;text-align:center;line-height:1.5;overflow-wrap:anywhere}
.context-card pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--pre-bg);padding:10px;border-radius:8px;max-height:22em;overflow:auto}
.batch-badge{position:absolute;top:8px;left:8px;background:#000d;color:#ffd98a;font-size:12.5px;font-weight:600;padding:5px 13px;border-radius:999px;cursor:pointer;z-index:2;border:1px solid #ffd98a66;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);transition:transform .12s ease,box-shadow .12s ease,background .12s ease}
.batch-badge:hover{transform:scale(1.07);background:#000f;box-shadow:0 2px 16px #0009;border-color:#ffd98a}
.loader{display:flex;align-items:center;justify-content:center;gap:10px;min-height:72px;padding:0 22px 26px}.loader .muted{font-size:12px}
#overlay{display:none;position:fixed;inset:0;background:#000d;z-index:12;align-items:center;justify-content:center;cursor:zoom-out}
#overlay img{max-width:92vw;max-height:92vh;border-radius:6px}.overlay-hint{position:fixed;bottom:18px;color:var(--chip-text);font-size:12px}
/* 组缩略图浮层：点徽标浮出组员缩略图（按数量缩放，整组一屏放下），点图看大图，点空白返回 */
#groupOverlay{display:none;position:fixed;inset:0;background:#000b;z-index:11;overflow:auto;backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);flex-direction:column}
#groupGrid{margin:auto;padding:28px;display:flex;flex-direction:row;flex-wrap:wrap;gap:18px;justify-content:center;align-content:center;align-items:center}
#groupGrid .cell img{width:100%;height:100%;object-fit:contain;display:block}
#groupGrid .gallery-item{width:auto;transition:transform .12s ease,border-color .12s ease}
#groupGrid .gallery-item:hover{transform:translateY(-2px);border-color:var(--accent)}
#groupHint{margin:0 auto 24px;color:var(--chip-text)}
</style></head><body>
__THEME_TOGGLE__
<header><a id="back" href="../index.html">← 返回</a><h1>__TITLE__</h1><div class="muted">共 __COUNT__ 张；滚动到末尾或点击按钮继续加载</div>
<div class="toolbar">
  <span id="progress" class="muted">已加载 0 / __COUNT__</span>
  <label class="muted" for="sortSel">排序</label>
  <select id="sortSel">
    <option value="">最新（时间）</option>
    <option value="chunks-size">文件大小</option>
    <option value="chunks-name">文件名称</option>
  </select>
  <input id="jumpTo" type="number" min="1" max="__COUNT__" placeholder="序号">
  <button id="topBtn" type="button">回顶部</button>
  <span id="collapseInfo" class="muted"></span>
</div>
</header>
<main><div id="grid" class="grid __GRID_CLASS__"></div>
<div id="loader" class="loader"><button id="loadMore" type="button">继续加载</button><span id="loadHint" class="muted">首批加载中…</span><span id="loadSentinel" aria-hidden="true"></span></div></main>
<div id="overlay"><img id="lightbox" src="" alt=""><span class="overlay-hint" id="overlayHint">Esc 关闭 · ←/→ 切换</span></div>
<div id="groupOverlay"><div id="groupGrid" class="grid"></div><span class="overlay-hint" id="groupHint"></span></div>
<script>
(() => {
  const total=__COUNT__, chunkCount=__CHUNK_COUNT__, contextMode=__CONTEXT_MODE__;
  const grid=document.getElementById('grid'), progress=document.getElementById('progress');
  const hint=document.getElementById('loadHint'), loadMore=document.getElementById('loadMore');
  const sentinel=document.getElementById('loadSentinel'), jump=document.getElementById('jumpTo');
  const overlay=document.getElementById('overlay'), lightbox=document.getElementById('lightbox');
  const cells=[], groups=new Map(), chunkPromises=new Map();
  let nextChunk=0, loading=false, activeRequest=null, currentIndex=-1, errorMessage='';
  let masked=true;
  let chunkBase='';
  try{masked=localStorage.getItem('maskRestored')!=='0';}catch(e){}
  try{chunkBase=['chunks-size','chunks-name'].includes(localStorage.getItem('gallerySort'))?localStorage.getItem('gallerySort'):'';}catch(e){}
  const sortSel=document.getElementById('sortSel');
  if(sortSel)sortSel.value=chunkBase;

  function updateProgress(){
    progress.textContent='已加载 '+cells.length+' / '+total;
    const done=nextChunk>=chunkCount&&!loading;
    loadMore.disabled=done;
    hint.textContent=errorMessage||(done?'已全部加载':'滚动到底部或点击“继续加载”');
    const known=[...groups.values()].filter(g=>g.total>1||g.cells.length>1).length;
    document.getElementById('collapseInfo').textContent=known?'已识别 '+known+' 组同批/相似（当前已加载部分）':'';
  }
  function applyMask(a){
    const image=a.querySelector('img');
    if(image) image.style.filter=masked&&a.dataset.masked==='1'?'blur(14px)':'none';
  }
  function updateGroup(group){
    // 主图库只显示代表图；组员通过大图浮层按组浏览（徽标点击进入）
    group.cards.forEach((card,i)=>{card.hidden=i>0;});
    if(group.total>1||group.cells.length>1){
      if(!group.badge){
        group.badge=document.createElement('span');
        group.badge.className='batch-badge';
        group.badge.dataset.batch=group.key;
        group.cards[0].appendChild(group.badge);
      }
      const kind=group.key.indexOf('dup')===0?'相似':'同批';
      group.badge.textContent=kind+' '+Math.max(group.total,group.cells.length)+' 张 · 点击查看';
    }
  }
  function registerGroup(a,item,card){
    // 折叠归属：相似组优先（画面相同），其次同批组（同一工作流）
    const key=String(item.dup||item.batch||'');
    if(!key)return;
    const total=Number((item.dup?item.dup_total:item.batch_total)||0);
    let group=groups.get(key);
    if(!group){group={key:key,page:'groups/'+key+'.js',total:total,cells:[],cards:[],badge:null};groups.set(key,group);}
    group.total=Math.max(group.total,total);
    group.cells.push(a); group.cards.push(card); updateGroup(group);
  }
  function markBroken(anchor,item){
    if(anchor.dataset.broken==='1')return;
    anchor.dataset.broken='1'; anchor.classList.add('broken');
    const image=anchor.querySelector('img'); if(image)image.remove();
    const placeholder=document.createElement('span'); placeholder.className='broken-image';
    placeholder.textContent='图片损坏 #'+String(item.id||'?')+'；请重发原图后执行“修复图片 '+String(item.id||'ID')+'”';
    anchor.appendChild(placeholder);
  }
  function createCard(item,index){
    const anchor=document.createElement('a');
    anchor.className='cell'; anchor.href=String(item.href||''); anchor.dataset.index=String(index);
    if(item.w&&item.h)anchor.style.aspectRatio=(Number(item.w)/Number(item.h)).toFixed(4);
    if(item.masked)anchor.dataset.masked='1';
    const image=document.createElement('img'); image.loading='lazy'; image.decoding='async'; image.alt='';
    // 缩略图加载失败先回退原图一次，原图也失败才标损坏
    image.addEventListener('error',()=>{
      if(item.thumb&&anchor.dataset.fallback!=='1'){anchor.dataset.fallback='1';image.src=String(item.href||'');return;}
      markBroken(anchor,item);
    });
    image.src=String(item.thumb||item.href||'');  // 卡片用小图，点开放大走 anchor.href 原图
    anchor.appendChild(image); applyMask(anchor);
    if(!contextMode){const card=document.createElement('div');card.className='gallery-item';card.appendChild(anchor);registerGroup(anchor,item,card);image.addEventListener('load',()=>layoutCard(card));return card;}
    const card=document.createElement('article'); card.className='context-card'; card.appendChild(anchor);
    if(item.label){const label=document.createElement('p');label.className='muted';label.textContent=String(item.label);card.appendChild(label);}
    if(item.text){const text=document.createElement('pre');text.textContent=String(item.text);card.appendChild(text);}
    registerGroup(anchor,item,card); return card;
  }
  const itemCards=[];
  const ROW_PX=8, ROW_GAP=10;
  function layoutCard(card){
    if(contextMode)return;
    const h=card.getBoundingClientRect().height;
    // 8px 行单元 + 10px 行距：跨 s 行时高度为 18s-10，需盖住卡片高度并留出下方间距
    if(h>0)card.style.gridRowEnd='span '+Math.max(1,Math.ceil((h+ROW_GAP*2)/(ROW_PX+ROW_GAP)));
  }
  function layoutAll(){for(const card of itemCards)layoutCard(card);}
  function renderItems(items){
    const fragment=document.createDocumentFragment();
    const fresh=[];
    for(const item of (Array.isArray(items)?items:[])){const index=cells.length;const card=createCard(item,index);cells.push(card.querySelector('a.cell'));itemCards.push(card);fresh.push(card);fragment.appendChild(card);}
    grid.appendChild(fragment);
    requestAnimationFrame(()=>{for(const card of fresh)layoutCard(card);});
    updateProgress();
  }
  window.__galleryAcceptChunk=(index,items)=>{
    const request=activeRequest;
    // base 校验：排序切换后，旧排序的 in-flight chunk 不得混入新排序的视图
    if(!request||request.base!==chunkBase||request.index!==index||request.settled)return;
    request.settled=true;request.accepted=true;request.resolve(items);
  };
  function loadChunk(index){
    if(index>=chunkCount)return Promise.resolve([]);
    if(chunkPromises.has(index))return chunkPromises.get(index);
    const promise=new Promise((resolve,reject)=>{
      const request={index:index,base:chunkBase,resolve:resolve,reject:reject,accepted:false,settled:false};activeRequest=request;
      const script=document.createElement('script');script.async=true;
      script.src=(chunkBase?chunkBase+'/':'chunks/')+'chunk-'+String(index+1).padStart(4,'0')+'.js';
      script.onload=()=>{if(request&&!request.accepted&&!request.settled){request.settled=true;reject(new Error('chunk callback missing'));}};
      script.onerror=()=>{if(!request.settled){request.settled=true;reject(new Error('chunk load failed'));}};
      document.head.appendChild(script);
    }).then(items=>{renderItems(items);nextChunk=Math.max(nextChunk,index+1);return items;}).finally(()=>{if(activeRequest&&activeRequest.index===index)activeRequest=null;});
    chunkPromises.set(index,promise);return promise;
  }
  async function loadNext(){
    if(loading||nextChunk>=chunkCount){updateProgress();return;}
    loading=true;errorMessage='';updateProgress();
    const index=nextChunk;
    try{await loadChunk(index);}catch(error){chunkPromises.delete(index);errorMessage='本批加载失败，点击“继续加载”重试';console.warn(error);}
    finally{loading=false;updateProgress();}
  }
  async function ensureLoaded(index){
    while(cells.length<=index&&nextChunk<chunkCount)await loadChunk(nextChunk);
  }
  function isPreviewVisible(anchor){return Boolean(anchor)&&!anchor.closest('[hidden]');}
  async function show(index){
    if(!total)return;
    index=((index%total)+total)%total;
    try{await ensureLoaded(index);}catch(error){errorMessage='目标图片加载失败';updateProgress();return;}
    const anchor=cells[index];if(!anchor)return;
    currentIndex=index;groupNav=null;if(overlayHint)hintDefault();
    lightbox.src=anchor.href;overlay.style.display='flex';
  }
  async function showAdjacent(delta){
    if(!total||currentIndex<0)return;
    let index=currentIndex;
    for(let scanned=0;scanned<total;scanned++){
      index=(index+delta+total)%total;
      try{await ensureLoaded(index);}catch(error){errorMessage='目标图片加载失败';updateProgress();return;}
      const anchor=cells[index];
      if(isPreviewVisible(anchor)){await show(index);return;}
    }
  }
  // ---- 组缩略图浮层：点徽标浮出组员缩略图，点图看大图（←/→ 组内切换），点空白返回 ----
  let groupNav=null, groupToken=0, lastGroup=null;
  const overlayHint=document.getElementById('overlayHint');
  const groupLayer=document.getElementById('groupOverlay'), groupGrid=document.getElementById('groupGrid'), groupHint=document.getElementById('groupHint');
  function hintDefault(){if(overlayHint)overlayHint.textContent='Esc 关闭 · ←/→ 切换';}
  function hintGroup(){if(overlayHint&&groupNav)overlayHint.textContent=groupNav.kind+'组 '+(groupNav.index+1)+'/'+groupNav.count+' · ←/→ 组内切换 · Esc 返回';}
  function closeGroupLayer(){groupLayer.style.display='none';groupGrid.textContent='';}
  function openGroup(group){
    lastGroup=group;
    const token=++groupToken;
    const script=document.createElement('script');
    script.src=group.page;
    document.head.appendChild(script);
    window.__galleryGroup=(data)=>{
      if(token!==groupToken)return;
      const members=Array.isArray(data&&data.members)?data.members:[];
      if(!members.length)return;
      const kind=String((data&&data.kind)||'组');
      // 从 1 行开始试：取能整组放下的最少行数 → 单图尺寸最大化；比例用原图的
      const n=members.length;
      const vw=window.innerWidth, vh=window.innerHeight;
      const availH=Math.max(220,vh-150), availW=Math.max(280,vw-96);
      const ratios=members.map(m=>(m.w&&m.h)?(Number(m.w)/Number(m.h)):0.75);
      const maxRatio=Math.max(0.4,...ratios);
      let rows=n, tileH=150;
      for(let r=1;r<=n;r++){
        const cols=Math.ceil(n/r);
        const h=Math.min(availH/r,(availW-(cols-1)*18)/(cols*maxRatio));
        if(h>=150){rows=r;tileH=h;break;}
      }
      tileH=Math.min(tileH,720);
      groupGrid.textContent='';
      const fragment=document.createDocumentFragment();
      const cells=members.map(m=>String(m.href||''));
      members.forEach((item,i)=>{
        const anchor=document.createElement('a');
        anchor.className='cell';anchor.href=String(item.href||'');
        const w=tileH*ratios[i];
        anchor.style.width=w.toFixed(1)+'px';
        anchor.style.height=tileH.toFixed(1)+'px';
        if(item.masked)anchor.dataset.masked='1';
        const image=document.createElement('img');image.loading='eager';image.decoding='async';image.alt='';
        image.addEventListener('error',()=>{if(item.thumb&&anchor.dataset.fallback!=='1'){anchor.dataset.fallback='1';image.src=String(item.href||'');}});
        image.src=String(item.thumb||item.href||'');
        anchor.appendChild(image);applyMask(anchor);
        anchor.addEventListener('click',event=>{
          event.preventDefault();
          if(masked&&anchor.dataset.masked==='1'){const im=anchor.querySelector('img');if(im)im.style.filter='none';delete anchor.dataset.masked;return;}
          groupNav={kind:kind,count:members.length,index:i,cells:cells};
          hintGroup();
          lightbox.src=anchor.href;
          overlay.style.display='flex';
        });
        const wrap=document.createElement('div');wrap.className='gallery-item';wrap.appendChild(anchor);
        fragment.appendChild(wrap);
      });
      groupGrid.appendChild(fragment);
      if(groupHint)groupHint.textContent=kind+'组 '+members.length+' 张 · 点图片看大图 · 点空白返回';
      groupLayer.style.display='flex';
    };
  }
  grid.addEventListener('click',event=>{
    const badge=event.target.closest('.batch-badge');
    if(badge&&grid.contains(badge)){
      event.preventDefault();event.stopPropagation();
      const group=groups.get(badge.dataset.batch);
      if(group)openGroup(group);
      return;
    }
    const anchor=event.target.closest('a.cell');
    if(!anchor||!grid.contains(anchor))return;
    event.preventDefault();
    if(anchor.dataset.broken==='1')return;
    if(masked&&anchor.dataset.masked==='1'){const image=anchor.querySelector('img');if(image)image.style.filter='none';delete anchor.dataset.masked;return;}
    void show(Number(anchor.dataset.index));
  });
  overlay.addEventListener('click',event=>{
    // 大图阶段点背景：返回缩略图浮层
    if(event.target===overlay){overlay.style.display='none';groupNav=null;hintDefault();}
  });
  groupLayer.addEventListener('click',event=>{
    // 缩略图阶段点图片交给图片处理；点其余任何地方（空白/缝隙）返回主图库
    if(event.target.closest('.cell'))return;
    closeGroupLayer();
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){
      if(overlay.style.display==='flex'){overlay.style.display='none';groupNav=null;hintDefault();return;}
      if(groupLayer.style.display==='flex'){closeGroupLayer();return;}
      return;
    }
    if(overlay.style.display!=='flex')return;
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
      event.preventDefault();
      const delta=event.key==='ArrowLeft'?-1:1;
      if(groupNav&&groupNav.cells.length){
        // 组内浏览：只在组内成员间切换
        groupNav.index=((groupNav.index+delta)%groupNav.cells.length+groupNav.cells.length)%groupNav.cells.length;
        lightbox.src=groupNav.cells[groupNav.index];
        hintGroup();
      }else{void showAdjacent(delta);}
    }
  });
  jump.addEventListener('keydown',event=>{if(event.key!=='Enter')return;const number=parseInt(jump.value,10);if(number<1||number>total)return;void ensureLoaded(number-1).then(()=>cells[number-1]?.scrollIntoView({block:'center'}));});
  document.getElementById('topBtn').addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));
  if(sortSel)sortSel.addEventListener('change',()=>{
    chunkBase=sortSel.value;
    try{localStorage.setItem('gallerySort',chunkBase);}catch(e){}
    // 重置状态后按新排序的分块目录重新加载
    cells.length=0;itemCards.length=0;groups.clear();chunkPromises.clear();nextChunk=0;currentIndex=-1;errorMessage='';
    groupNav=null;groupToken++;closeGroupLayer();hintDefault();
    overlay.style.display='none';grid.textContent='';
    updateProgress();void loadNext();
  });
  let rsTimer=0;
  window.addEventListener('resize',()=>{clearTimeout(rsTimer);rsTimer=setTimeout(()=>{layoutAll();if(groupLayer.style.display==='flex'&&lastGroup)openGroup(lastGroup);},200);});
  loadMore.addEventListener('click',()=>void loadNext());
  if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))void loadNext();},{rootMargin:'900px'});observer.observe(sentinel);}
  updateProgress();void loadNext();
  // 壁纸放最后加载：首屏先渲染卡片，空闲时再换上大背景
  const setWallpaper=function(){("requestIdleCallback"in window?requestIdleCallback:function(f){setTimeout(f,200)})(function(){document.body.classList.add("wallpaper-ready")},{timeout:2000})};
  document.readyState!=="loading"?setWallpaper():document.addEventListener("DOMContentLoaded",setWallpaper);
})();
</script>
__THEME_TOGGLE_JS__
</body></html>'''
    replacements = {
        '__TITLE__': html.escape(title),
        '__COUNT__': str(int(count)),
        '__CHUNK_COUNT__': str(int(chunk_count)),
        '__CONTEXT_MODE__': 'true' if context_mode else 'false',
        '__GRID_CLASS__': 'context-grid' if context_mode else '',
        '__WALLPAPER_CSS__': background,
        '__THEME_VARS__': THEME_VARS_CSS,
        '__THEME_INIT__': THEME_INIT_JS,
        '__THEME_TOGGLE__': THEME_TOGGLE_HTML,
        '__THEME_TOGGLE_JS__': THEME_TOGGLE_JS,
    }
    for marker, value in replacements.items():
        doc = doc.replace(marker, value)
    return doc


def _gallery_background(cat_dir: Path) -> str:
    from .view_theme import background_css, find_wallpaper

    wallpaper = find_wallpaper(cat_dir.parent)
    return background_css('../' + wallpaper if wallpaper else None)


def write_category_gallery(
    cat_dir: Path,
    *,
    project_dir: Path | None = None,
    thumb_prefix: str = '../..',
    force: bool = False,
    dhash_cache: '_DhashCache | None' = None,
) -> None:
    '''为图片分类目录生成单页按需图库；只加载首批，滚动后再追加本地 chunk。'''
    if not force and (cat_dir / 'index.html').exists():
        return  # 已有专门页面（如 03_提示词绑定）则不覆盖
    image_exts = IMAGE_EXTENSIONS
    # 缩略图缓存在 data/view-thumbs（视图目录重建不清掉），卡片加载小图、点开看原图
    thumbs_root = (project_dir / 'data' / THUMBS_DIR) if project_dir else None
    thumb_rel_dir = safe_name(cat_dir.name)

    def image_id(p: Path) -> int:
        try:
            return int(p.stem.split('_')[0].lstrip('#'))
        except (ValueError, IndexError):
            return 0

    def image_wh(p: Path) -> tuple[int, int]:
        match = re.search(r'_(\d+)x(\d+)_', p.name)
        return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

    images = sorted(
        (p for p in cat_dir.rglob('*') if p.is_file() and p.suffix.lower() in image_exts),
        key=lambda p: image_id(p),
        reverse=True,
    )
    if not images:
        return
    batch_totals: dict[str, int] = {}
    for image in images:
        key = _gallery_batch_key(image.name)
        if key:
            batch_totals[key] = batch_totals.get(key, 0) + 1
    gallery_items: list[dict[str, object]] = []
    hash_entries: list[tuple[str, int, tuple[int, int]]] = []
    for image in images:
        rel = os.path.relpath(image, cat_dir).replace(os.sep, '/')
        batch = _gallery_batch_key(image.name)
        width, height = image_wh(image)
        image_key = image.stem.split('_', 1)[0].lstrip('#')
        thumb = ''
        if thumbs_root:
            key = image.stem
            thumb_path = thumbs_root / thumb_rel_dir / (key + '.jpg')
            if _thumb_file(image, thumb_path):
                thumb = f'{thumb_prefix}/{THUMBS_DIR}/{url_path(thumb_rel_dir)}/{url_path(key)}.jpg'
                # 视觉去重基于缩略图：md5 精确命中 + dhash 近似命中（原图已解码过一次的成本不必重复）
                if dhash_cache is not None:
                    looked = dhash_cache.lookup(thumb_path)
                    digest, thumb_md5 = looked if looked is not None else (0, '')
                else:
                    digest = _dhash(thumb_path) if thumb_path.exists() else 0
                    thumb_md5 = _thumb_md5(thumb_path) if thumb_path.exists() else ''
                hash_entries.append((image_key, digest, (width, height), thumb_md5))
        try:
            size_bytes = image.stat().st_size
        except OSError:
            size_bytes = 0
        gallery_items.append({
            'href': url_path(rel),
            'id': image_key,
            'masked': '还原' in image.name,
            'batch': batch,
            'batch_total': batch_totals.get(batch, 0),
            'w': width,
            'h': height,
            'bytes': size_bytes,
            'thumb': thumb,
        })
    # 视觉相同的图折叠：dup 组优先于"同批"键（NovelAI 等批量同图重发场景）。
    # 两条分组关系并存（dup 字段不覆盖 batch）：相似组管主图折叠徽标，
    # 同批组的浮层浏览仍能看到该工作流的全部图——否则徽标数量会对不上。
    dup_groups = _assign_dup_groups(hash_entries)
    dup_totals: dict[str, int] = {}
    if dup_groups:
        for group_id in dup_groups.values():
            dup_totals[group_id] = dup_totals.get(group_id, 0) + 1
        for item in gallery_items:
            group_id = dup_groups.get(str(item['id']))
            if group_id:
                item['dup'] = group_id
                item['dup_total'] = dup_totals.get(group_id, 0)
    # 组数据文件：每个相似/同批组一个小 .js，点徽标按需加载，
    # 在现有查看大图的浮层里按组切换（成员可能尚未随分块加载到主页）
    group_members: dict[str, list[dict[str, object]]] = {}
    for item in gallery_items:
        dup_key = str(item.get('dup') or '')
        if dup_key:
            group_members.setdefault(dup_key, []).append(item)
        batch_key = str(item.get('batch') or '')
        if batch_key and int(item.get('batch_total') or 0) > 1:
            group_members.setdefault(batch_key, []).append(item)
    if group_members:
        groups_dir = cat_dir / 'groups'
        shutil.rmtree(groups_dir, ignore_errors=True)
        groups_dir.mkdir(parents=True, exist_ok=True)
        for key, members in sorted(group_members.items()):
            fname = _group_data_file(key)
            kind = '相似' if key.startswith('dup') else '同批'
            payload = {
                'key': key,
                'kind': kind,
                'count': len(members),
                'members': members,
            }
            (groups_dir / (fname + '.js')).write_text(
                f'window.__galleryGroup({_script_json(payload)});\n', encoding='utf-8')
    else:
        shutil.rmtree(cat_dir / 'groups', ignore_errors=True)
    chunk_count = _write_gallery_chunk_sets(cat_dir, gallery_items)
    (cat_dir / 'index.html').write_text(
        _gallery_page(title=cat_dir.name, count=len(gallery_items), chunk_count=chunk_count,
                      background=_gallery_background(cat_dir)),
        encoding='utf-8',
    )


def _write_context_gallery(
    cat_dir: Path,
    items: list[dict[str, object]],
    title: str,
    *,
    project_dir: Path | None = None,
    thumb_prefix: str = '../..',
) -> None:
    '''上下文分类也使用单页按需加载，文本随对应本地 chunk 追加。'''
    cat_dir.mkdir(parents=True, exist_ok=True)
    thumbs_root = (project_dir / 'data' / THUMBS_DIR) if project_dir else None
    thumb_rel_dir = safe_name(cat_dir.name)
    gallery_items: list[dict[str, object]] = []
    for item in items:
        thumb = ''
        if thumbs_root and project_dir:
            src = project_dir / 'data' / 'view' / cat_dir.name / str(item['image_rel'])
            if src.exists() and _thumb_file(src, thumbs_root / thumb_rel_dir / (Path(str(item['image_rel'])).stem + '.jpg')):
                key = Path(str(item['image_rel'])).stem
                thumb = f'{thumb_prefix}/{THUMBS_DIR}/{url_path(thumb_rel_dir)}/{url_path(key)}.jpg'
        gallery_items.append({
            'href': url_path(str(item['image_rel'])),
            'masked': bool(item.get('deobfuscated')),
            'label': f"#{item['id']} · {item['meta']}",
            'text': str(item.get('text') or ''),
            'batch': '',
            'batch_total': 0,
            'w': int(item.get('w') or 0),
            'h': int(item.get('h') or 0),
            'thumb': thumb,
        })
    if not gallery_items:
        return
    chunk_count = _write_gallery_chunks(cat_dir, gallery_items)
    (cat_dir / 'index.html').write_text(
        _gallery_page(title=title, count=len(gallery_items), chunk_count=chunk_count,
                      context_mode=True, background=_gallery_background(cat_dir)),
        encoding='utf-8',
    )


def write_prompt_bound_gallery(cat_dir: Path, items: list[dict[str, object]], **kwargs) -> None:
    _write_context_gallery(cat_dir, items, '03 提示词绑定', **kwargs)


def write_params_gallery(cat_dir: Path, items: list[dict[str, object]], **kwargs) -> None:
    _write_context_gallery(cat_dir, items, '03 参数讨论', **kwargs)


GENERATOR_VERSION = 18  # 页面/文件名规则变化时 +1：签名状态作废，下一次构建按全量处理

_CONTEXT_CAT_NAMES = {CATEGORY_NAMES['prompt_bound'], CATEGORY_NAMES['params_discussion']}
_SAVED_ROOT = '06_聊天记录收藏'


class _CatPlan:
    """一个类目目录的期望状态：应存在的图片（相对路径 -> 源文件）与上下文条目。

    完全由数据库推导，与磁盘现状无关；签名一致即认为该类目无需重建。
    """

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.items: list[dict[str, object]] = []

    def signature(self) -> str:
        h = hashlib.sha1()
        for rel in sorted(self.files):
            h.update(rel.encode('utf-8'))
            h.update(b'\x1f')
            h.update(self.files[rel].encode('utf-8'))
            h.update(b'\x1e')
        for item in self.items:
            h.update(repr(sorted((k, str(v)) for k, v in item.items())).encode('utf-8'))
            h.update(b'\x1e')
        return h.hexdigest()


def _build_state_path(project_dir: Path) -> Path:
    return project_dir / 'data' / 'view-build-state.json'


def _load_build_state(project_dir: Path) -> dict:
    try:
        state = json.loads(_build_state_path(project_dir).read_text(encoding='utf-8'))
    except Exception:
        return {'version': GENERATOR_VERSION, 'categories': {}}
    if not isinstance(state, dict) or state.get('version') != GENERATOR_VERSION:
        return {'version': GENERATOR_VERSION, 'categories': {}}
    if not isinstance(state.get('categories'), dict):
        state['categories'] = {}
    return state


def _save_build_state(project_dir: Path, state: dict) -> None:
    try:
        _write_if_changed(_build_state_path(project_dir),
                          json.dumps(state, ensure_ascii=False))
    except OSError:
        pass


_DHASH_SIGN = 1 << 63  # dhash 是 64 位无符号值，SQLite INTEGER 是有符号 64 位，入库需转换


def _dhash_to_db(digest: int) -> int:
    return digest - (1 << 64) if digest >= _DHASH_SIGN else digest


def _dhash_from_db(value: int) -> int:
    return value + (1 << 64) if value < 0 else value


class _DhashCache:
    """缩略图 dhash+md5 的跨重建缓存（bot.db 里的 view_dhash 表）。

    key 是 (路径, mtime, size)，缩略图一旦重新生成会自动重算。命中时省掉
    全部缩略图的 PIL 解码——这是整次重建里最耗时的部分（2 万多张要数分钟）。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.execute(
            'CREATE TABLE IF NOT EXISTS view_dhash '
            '(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, dhash INTEGER)'
        )
        try:
            conn.execute('ALTER TABLE view_dhash ADD COLUMN md5 TEXT')
        except sqlite3.OperationalError:
            pass  # 列已存在
        conn.commit()
        self.rows: dict[str, tuple[int, int, int, str]] = {
            str(row[0]): (int(row[1]), int(row[2]), _dhash_from_db(int(row[3])), str(row[4] or ''))
            for row in conn.execute('SELECT path, mtime, size, dhash, md5 FROM view_dhash')
        }
        self.pending: dict[str, tuple[int, int, int, str]] = {}

    def lookup(self, path: Path) -> tuple[int, str] | None:
        """返回 (dhash, 缩略图md5)；文件不存在时返回 None。"""
        try:
            st = path.stat()
        except OSError:
            return None
        mtime, size = int(st.st_mtime), st.st_size
        key = str(path)
        cached = self.pending.get(key) or self.rows.get(key)
        if cached and cached[0] == mtime and cached[1] == size:
            if cached[3]:
                return cached[2], cached[3]
            # 旧版本缓存只有 dhash：沿用缓存值，补算 md5（缩略图小，成本低）
            entry = (mtime, size, cached[2], _thumb_md5(path))
            self.pending[key] = entry
            self.rows[key] = entry
            return entry[2], entry[3]
        entry = (mtime, size, _dhash(path), _thumb_md5(path))
        self.pending[key] = entry
        self.rows[key] = entry
        return entry[2], entry[3]

    def flush(self) -> None:
        if not self.pending:
            return
        self.conn.executemany(
            'INSERT INTO view_dhash (path, mtime, size, dhash, md5) VALUES (?,?,?,?,?) '
            'ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, '
            'dhash=excluded.dhash, md5=excluded.md5',
            [(key, entry[0], entry[1], _dhash_to_db(entry[2]), entry[3])
             for key, entry in self.pending.items()],
        )
        self.conn.commit()
        self.pending.clear()


def _existing_image_rels(cat_dir: Path) -> set[str]:
    out: set[str] = set()
    if cat_dir.is_dir():
        for p in cat_dir.rglob('*'):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                out.add(os.path.relpath(p, cat_dir).replace(os.sep, '/'))
    return out


def _cat_page_intact(cat_dir: Path, *, context: bool) -> bool:
    """页面骨架是否完整：index.html + 需要的 chunk 集（供跳过判定兜底）。"""
    if not (cat_dir / 'index.html').exists():
        return False
    subs = ('chunks',) if context else ('chunks', 'chunks-size', 'chunks-name')
    for sub in subs:
        d = cat_dir / sub
        if not d.is_dir() or not any(d.glob('chunk-*.js')):
            return False
    return True


def _apply_cat_plan(cat_dir: Path, plan: _CatPlan, copy_fallbacks: list[tuple[Path, Path]]) -> None:
    """把类目目录调整到期望状态：删多余图片文件、补缺失链接，未变化的不动。"""
    existing = _existing_image_rels(cat_dir)
    for rel in existing - plan.files.keys():
        try:
            (cat_dir / rel).unlink()
        except OSError:
            pass
    for rel, src_str in plan.files.items():
        dst = cat_dir / rel
        if rel in existing and dst.exists():
            continue  # 文件名编码了 id/尺寸/标记，存在即视为正确
        mode = make_link_or_copy(Path(src_str), dst)
        if mode == 'copy':
            copy_fallbacks.append((Path(src_str), dst))
    for sub in list(cat_dir.iterdir()):
        if sub.is_dir() and not any(sub.iterdir()):
            try:
                sub.rmdir()
            except OSError:
                pass


def build_view(project_dir: Path) -> dict[str, int]:
    """构建/增量更新图片视图目录。

    每个类目的期望状态完全由数据库推导；签名与上次一致、页面骨架完整、
    磁盘文件齐全的类目原样跳过。不再整目录删除重建，页面上不存在
    "先删后建"的空窗；缩略图 dhash 也有跨重建缓存（见 _DhashCache）。
    """
    db = project_dir / 'data' / 'bot.db'
    view = project_dir / 'data' / 'view'
    view.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    image_cols = {row[1] for row in conn.execute('PRAGMA table_info(images)')}
    sha256_col = 'sha256, ' if 'sha256' in image_cols else "'' AS sha256, "
    saved_category_col = 'saved_category, ' if 'saved_category' in image_cols else "'' AS saved_category, "
    restored_col = 'restored_path, ' if 'restored_path' in image_cols else "'' AS restored_path, "
    deobfuscated_col = 'deobfuscated, ' if 'deobfuscated' in image_cols else '0 AS deobfuscated, '
    binding_cols = 'bound_prompt, prompt_key, context_reason, ' if 'bound_prompt' in image_cols else "'' AS bound_prompt, '' AS prompt_key, '' AS context_reason, "
    rows = conn.execute(
        '''SELECT id, ''' + sha256_col + saved_category_col + '''scope, user_id, seen_at, format, width, height, size, has_ai_metadata, ai_source, retention_reason, kept_path, ''' + restored_col + deobfuscated_col + binding_cols + '''text_excerpt, raw_json
           FROM images WHERE kept_path IS NOT NULL ORDER BY retention_reason, id DESC'''
    ).fetchall()
    dhash_cache = _DhashCache(conn)
    plans: dict[str, _CatPlan] = {}
    saved_categories: set[str] = set()
    dedup_seen: dict[str, set[str]] = {}
    # 同批判定：同一完整工作流签名 且 组大小 2..30 且 时间跨度 ≤ 24 小时
    batch_keys: set[str] = set()
    if 'prompt_key' in image_cols:
        from datetime import datetime as _dt
        try:
            for pk, cnt, mn, mx in conn.execute(
                "SELECT prompt_key, COUNT(*), MIN(seen_at), MAX(seen_at) FROM images "
                "WHERE retention_reason='ai_metadata' AND prompt_key IS NOT NULL GROUP BY prompt_key"
            ).fetchall():
                if not (2 <= int(cnt) <= 30):
                    continue
                def _ts(v: object):
                    try:
                        return _dt.fromisoformat(str(v).replace('T', ' '))
                    except Exception:
                        return None
                t1, t2 = _ts(mn), _ts(mx)
                if t1 and t2 and (t2 - t1).total_seconds() <= 24 * 3600:
                    batch_keys.add(str(pk))
        except Exception:
            batch_keys = set()
    for row in rows:
        src = source_path(project_dir, row['kept_path'])
        if not src.exists():
            continue
        sha256 = str(row['sha256'] or '') if 'sha256' in row.keys() else ''
        reason = row['retention_reason'] or 'unknown'
        if reason == 'chat_record_saved':
            category = saved_category_name(row['saved_category'] if 'saved_category' in row.keys() else '')
            saved_categories.add(category)
            saved_key = f'{_SAVED_ROOT}/{category}'
            if sha256:
                seen = dedup_seen.setdefault(saved_key, set())
                if sha256 in seen:
                    continue
                seen.add(sha256)
            w, h = row['width'], row['height']
            ext = src.suffix or '.img'
            filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}") + ext
            plans.setdefault(saved_key, _CatPlan()).files[filename] = str(src)
            continue
        cat = CATEGORY_NAMES.get(reason, '90_' + safe_name(reason))
        if reason == 'ai_metadata' and row['ai_source']:
            cat = cat + '_' + safe_name(str(row['ai_source']))
        # 03/05 分类按 sha 去重：同一张图（同 sha）只显示最新一条
        if reason in ('prompt_bound', 'params_discussion', 'xiaofanqie_obfuscated'):
            seen = dedup_seen.setdefault(cat, set())
            if sha256 and sha256 in seen:
                continue
            seen.add(sha256)
        size_class = 'unknown_size'
        w, h = row['width'], row['height']
        if w and h:
            if w >= h * 1.2:
                size_class = '横图'
            elif h >= w * 1.2:
                size_class = '竖图'
            else:
                size_class = '方图'
        ext = src.suffix or '.img'
        is_deobfuscated = bool(row['deobfuscated']) if 'deobfuscated' in row.keys() else False
        # 遮罩标记只加在 02/03（05 小番茄混淆不遮罩）
        mask_marker = '_还原' if (is_deobfuscated and reason in ('positive_feedback', 'prompt_bound', 'params_discussion')) else ''
        pk = str(row['prompt_key'] or '')[:8] if (
            'prompt_key' in row.keys() and row['prompt_key'] and str(row['prompt_key']) in batch_keys
        ) else ''
        filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}{mask_marker}{'_pk' + pk if pk else ''}") + ext
        plan = plans.setdefault(cat, _CatPlan())
        plan.files[f'{size_class}/{filename}'] = str(src)
        if reason in ('prompt_bound', 'params_discussion'):
            plan.items.append({
                'id': str(row['id']),
                'image_rel': f'{size_class}/{filename}',
                'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                'text': str(row['bound_prompt'] or ''),
                'deobfuscated': is_deobfuscated,
                'w': row['width'] or 0,
                'h': row['height'] or 0,
            })
        # 05 的确认混淆图按 context_reason 交叉显示到 02/03（遮罩标记）
        context_reason = row['context_reason'] if 'context_reason' in row.keys() else None
        if context_reason and context_reason in CATEGORY_NAMES:
            context_cat = CATEGORY_NAMES[context_reason]
            seen_ctx = dedup_seen.setdefault(context_cat, set())
            if not (sha256 and sha256 in seen_ctx):
                if sha256:
                    seen_ctx.add(sha256)
                ctx_filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}_还原") + ext
                ctx_plan = plans.setdefault(context_cat, _CatPlan())
                ctx_plan.files[f'{size_class}/{ctx_filename}'] = str(src)
                if context_reason in ('prompt_bound', 'params_discussion'):
                    ctx_plan.items.append({
                        'id': str(row['id']),
                        'image_rel': f'{size_class}/{ctx_filename}',
                        'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                        'text': str(row['bound_prompt'] or ''),
                        'deobfuscated': True,
                        'w': row['width'] or 0,
                        'h': row['height'] or 0,
                    })
    state = _load_build_state(project_dir)
    counts: dict[str, int] = {}
    copy_fallbacks: list[tuple[Path, Path]] = []
    dirty: list[tuple[str, _CatPlan]] = []
    for cat_name in sorted(plans):
        plan = plans[cat_name]
        cat_dir = view / cat_name
        if not plan.files:
            if cat_dir.exists():
                shutil.rmtree(cat_dir, ignore_errors=True)
            state['categories'].pop(cat_name, None)
            continue
        sig = plan.signature()
        prev = state['categories'].get(cat_name)
        context = cat_name in _CONTEXT_CAT_NAMES
        if (prev and prev.get('sig') == sig
                and _cat_page_intact(cat_dir, context=context)
                and _existing_image_rels(cat_dir) == plan.files.keys()):
            counts[cat_name] = int(prev.get('count') or len(plan.files))
            continue
        try:
            _apply_cat_plan(cat_dir, plan, copy_fallbacks)
        except Exception as exc:
            print(f'view placement failed for {cat_name}: {type(exc).__name__}: {exc}')
            continue
        counts[cat_name] = len(plan.files)
        state['categories'][cat_name] = {'sig': sig, 'count': len(plan.files)}
        dirty.append((cat_name, plan))
    # 状态里已消失的类目：清掉记录；磁盘上已无类目对应的目录：删掉
    for cat_name in [c for c in state['categories'] if c not in plans]:
        del state['categories'][cat_name]
    planned_roots = {name.split('/', 1)[0] for name in plans}
    if view.is_dir():
        for p in list(view.iterdir()):
            if p.is_dir() and p.name not in planned_roots:
                shutil.rmtree(p, ignore_errors=True)
    saved_root = view / _SAVED_ROOT
    if saved_root.is_dir():
        planned_subs = {name.split('/', 1)[1] for name in plans if name.startswith(_SAVED_ROOT + '/')}
        for p in list(saved_root.iterdir()):
            if p.is_dir() and p.name not in planned_subs:
                shutil.rmtree(p, ignore_errors=True)
    # 只为有变化的类目重新生成图库页
    for cat_name, plan in dirty:
        cat_dir = view / cat_name
        try:
            if cat_name in _CONTEXT_CAT_NAMES and plan.items:
                if cat_name == CATEGORY_NAMES['prompt_bound']:
                    write_prompt_bound_gallery(cat_dir, plan.items, project_dir=project_dir)
                else:
                    write_params_gallery(cat_dir, plan.items, project_dir=project_dir)
            else:
                # 收藏子分类页面深一层，缩略图路径多退一级
                thumb_prefix = '../../..' if cat_name.startswith(_SAVED_ROOT + '/') else '../..'
                write_category_gallery(cat_dir, project_dir=project_dir, thumb_prefix=thumb_prefix,
                                       force=True, dhash_cache=dhash_cache)
        except Exception as exc:
            print(f'gallery generation failed for {cat_name}: {type(exc).__name__}: {exc}')
    if copy_fallbacks:
        remaining = [dst for src, dst in copy_fallbacks if not relink_view_copy(src, dst)]
        if remaining:
            print(f'view hardlink warning: {len(remaining)} files stayed as copies '
                  f'(os.link failed); rerun maintenance to retry')
    wallpaper_name = _make_wallpaper(project_dir, view, conn)
    if wallpaper_name:
        print(f'view wallpaper: {wallpaper_name}')
    if saved_categories:
        write_saved_collection_index(saved_root, saved_categories)
    dhash_cache.flush()
    conn.close()
    # 资源/文件页（build_view 会清空视图目录，必须一并重建）
    try:
        from .resource_view import write_resource_pages
        from .store import Store
        from .config import load_config
        _cfg = load_config(project_dir / 'config.yaml')
        resource_counts = write_resource_pages(
            view,
            Store(project_dir / 'data' / 'bot.db'),
            link_judge_mode=_cfg.links_link_judge,
        )
        counts.update(resource_counts)
    except Exception as exc:
        print(f'resource pages failed: {type(exc).__name__}: {exc}')
    readme = view / 'README.txt'
    _write_if_changed(
        readme,
        '这是图片分类视图，按数据库筛选结果生成。\n'
        '优先使用 NTFS 硬链接，通常不额外占空间；不要在这里编辑原始数据库。\n\n'
        '分类：\n'
        '01_AI元数据_*：图片本身带 ComfyUI/NovelAI 等元数据，可信度最高。\n'
        '02_群友好评：被引用/附近好评、求提示词等晋升。\n'
        '03_提示词绑定：图片与明确提示词成对绑定（时序/引用）。\n'
        '03_参数讨论：无提示词但附近提到模型/采样器/显卡等参数。\n'
        '04_候选待观察：暂存，等待后续反馈。\n'
        '05_小番茄混淆：经 Gilbert 曲线逆置换验证的混淆图（算法级确认）。\n'
        '05_小番茄混淆_压缩：重压/缩放后的混淆图（弱信号，逆置换无法完全还原）。\n',
    )
    write_view_index(view, counts)
    _save_build_state(project_dir, state)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-dir', default='.')
    args = parser.parse_args()
    counts = build_view(Path(args.project_dir).resolve())
    for key, value in sorted(counts.items()):
        print(f'{key}: {value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

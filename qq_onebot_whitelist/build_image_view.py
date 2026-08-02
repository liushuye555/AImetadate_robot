from __future__ import annotations

from pathlib import Path
import argparse
import html
import json
import os
import re
import shutil
import sqlite3
from urllib.parse import quote

from .context_view import build_context_view

CATEGORY_NAMES = {
    'ai_metadata': '01_AI元数据',
    'positive_feedback': '02_群友好评',
    'nearby_ai_context': '03_AI上下文',
    'candidate': '04_候选待观察',
    'xiaofanqie_obfuscated': '05_小番茄混淆',
    'xiaofanqie_compressed': '05_小番茄混淆_压缩',
    'no_ai_metadata': '99_普通无元数据',
}


def stale_view_counts(view: Path) -> dict[str, int]:
    """不重建视图，直接从现有视图目录统计各分类图片数（低开销，供负载忙时兜底）。"""
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
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


def write_view_index(view: Path, counts: dict[str, int]) -> None:
    categories = sorted([p for p in view.iterdir() if p.is_dir()], key=lambda p: p.name) if view.exists() else []
    cards = []
    fixed_pages = [
        ('resources.html', '高价值资源链接', '已过滤低价值分享，按群分类去重'),
        ('files.html', '高价值文件/工作流', '文件名、类型、大小；不展示长下载 URL'),
    ]
    for href, title, desc in fixed_pages:
        cards.append(
            '<article class="card">'
            f'<h2><a href="{html.escape(url_path(href))}">{html.escape(title)}</a></h2>'
            f'<p class="muted">{html.escape(desc)}</p>'
            '</article>'
        )
    for cat_dir in categories:
        count = counts.get(cat_dir.name)
        if count is None:
            count = sum(1 for p in cat_dir.rglob('*') if p.is_file() and p.name != 'index.html')
        target = cat_dir.name + ('/index.html' if (cat_dir / 'index.html').exists() else '/')
        cards.append(
            '<article class="card">'
            f'<h2><a href="{html.escape(url_path(target))}">{html.escape(cat_dir.name)}</a></h2>'
            f'<p class="muted">{int(count)} 张</p>'
            '</article>'
        )
    if not cards:
        cards.append('<article class="card"><h2>暂无图片分类</h2><p class="muted">等待维护脚本生成。</p></article>')
    doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>QQ AI 图片视图</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:24px;background:#101114;color:#eee}
a{color:#8ab4ff;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.card{padding:18px;background:#181a20;border:1px solid #2b2f3a;border-radius:14px}.muted{color:#aaa}
</style><body><h1>QQ AI 图片视图</h1>
<p class="muted">分类视图入口；03_AI上下文 有专门 HTML 页面，其它分类可直接浏览目录图片。</p>
<div class="grid">''' + '\n'.join(cards) + '</div></body></html>'
    view.mkdir(parents=True, exist_ok=True)
    (view / 'index.html').write_text(doc, encoding='utf-8')


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


def write_category_gallery(cat_dir: Path) -> None:
    """为图片分类目录生成图库页（缩略图网格 + 灯箱预览）。"""
    if (cat_dir / 'index.html').exists():
        return  # 已有专门页面（如 03_AI上下文）则不覆盖
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    images = sorted(
        (p for p in cat_dir.rglob('*') if p.is_file() and p.suffix.lower() in image_exts),
        key=lambda p: str(p).lower(),
    )
    if not images:
        return
    rels = [os.path.relpath(p, cat_dir).replace(os.sep, '/') for p in images]
    cells = ''.join(
        f'<a class="cell" href="{url_path(r)}"><img loading="lazy" src="{url_path(r)}" alt=""></a>'
        for r in rels
    )
    doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{title}</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#0d0f13;color:#eef1f6}}
header{{padding:18px 22px;position:sticky;top:0;background:#0d0f13ee;backdrop-filter:blur(8px);z-index:2;border-bottom:1px solid #262d3a}}
h1{{font-size:18px;margin:0 0 4px}}
.muted{{color:#8b96a8;font-size:13px}}
#back{{color:#8ab4ff;text-decoration:none;font-size:13px;margin-right:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;padding:16px 22px}}
.cell{{display:block;border-radius:8px;overflow:hidden;background:#171b23}}
.cell img{{width:100%;height:180px;object-fit:cover;display:block}}
#overlay{{display:none;position:fixed;inset:0;background:#000d;z-index:10;align-items:center;justify-content:center;cursor:zoom-out}}
#overlay img{{max-width:92vw;max-height:92vh;border-radius:6px}}
</style></head><body>
<header><a id="back" href="../index.html">← 返回</a><h1>{title}</h1><div class="muted">{count} 张</div></header>
<div class="grid">{cells}</div>
<div id="overlay"><img id="lightbox" src=""></div>
<script>
const cells=[...document.querySelectorAll('.cell')];const overlay=document.getElementById('overlay');const img=document.getElementById('lightbox');let cur=0;
function show(i){{cur=(i+cells.length)%cells.length;img.src=cells[cur].href;overlay.style.display='flex';}}
cells.forEach((a,i)=>a.addEventListener('click',e=>{{e.preventDefault();show(i);}}));
overlay.addEventListener('click',e=>{{if(e.target===overlay)overlay.style.display='none';}});
document.addEventListener('keydown',e=>{{if(overlay.style.display==='flex'){{if(e.key==='Escape')overlay.style.display='none';if(e.key==='ArrowLeft')show(cur-1);if(e.key==='ArrowRight')show(cur+1);}}}});
</script></body></html>'''.format(
        title=html.escape(cat_dir.name),
        count=len(images),
        cells=cells,
    )
    (cat_dir / 'index.html').write_text(doc, encoding='utf-8')


def build_view(project_dir: Path) -> dict[str, int]:
    db = project_dir / 'data' / 'bot.db'
    view = project_dir / 'data' / 'view'
    if view.exists():
        shutil.rmtree(view)
    view.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    image_cols = {row[1] for row in conn.execute('PRAGMA table_info(images)')}
    restored_col = 'restored_path, ' if 'restored_path' in image_cols else ''
    rows = conn.execute(
        '''SELECT id, scope, user_id, seen_at, format, width, height, size, has_ai_metadata, ai_source, retention_reason, kept_path, ''' + restored_col + '''text_excerpt, raw_json
           FROM images WHERE kept_path IS NOT NULL ORDER BY retention_reason, id DESC'''
    ).fetchall()
    group_names = group_name_map_from_conn(conn)
    counts: dict[str, int] = {}
    context_items: list[dict[str, object]] = []
    for row in rows:
        src = source_path(project_dir, row['kept_path'])
        if not src.exists():
            continue
        reason = row['retention_reason'] or 'unknown'
        cat = CATEGORY_NAMES.get(reason, '90_' + safe_name(reason))
        if reason == 'ai_metadata' and row['ai_source']:
            cat = cat + '_' + safe_name(str(row['ai_source']))
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
        filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}_{row['ai_source'] or ''}") + ext
        dst = view / cat / size_class / filename
        mode = make_link_or_copy(src, dst)
        counts[cat] = counts.get(cat, 0) + 1
        # 已自动解混淆的图片：把还原图一并放进分类，方便直接查看原内容
        restored_path = row['restored_path'] if 'restored_path' in row.keys() else None
        if restored_path:
            restored_src = source_path(project_dir, restored_path)
            if restored_src.exists():
                restored_name = safe_name(
                    f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}_解混淆"
                ) + restored_src.suffix
                restored_dst = view / cat / size_class / restored_name
                make_link_or_copy(restored_src, restored_dst)
                counts[cat] = counts.get(cat, 0) + 1
        if reason == 'nearby_ai_context':
            try:
                raw = json.loads(row['raw_json'] or '{}')
                message_db_id = int(raw['message_db_id']) if raw.get('message_db_id') is not None else None
            except Exception:
                message_db_id = None
            image_rel = os.path.relpath(dst, view / cat).replace(os.sep, '/')
            context_items.append({
                'id': str(row['id']),
                'scope': str(row['scope'] or ''),
                'image_rel': image_rel,
                'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                'seen_at': str(row['seen_at'] or ''),
                'text_excerpt': str(row['text_excerpt'] or ''),
                'message_db_id': message_db_id,
            })
    build_context_view(conn, view / CATEGORY_NAMES['nearby_ai_context'], context_items, group_names)
    conn.close()
    # 为每个分类生成图库页（已存在专门页面的分类跳过）
    for cat_dir in sorted((p for p in view.iterdir() if p.is_dir()), key=lambda p: p.name):
        try:
            write_category_gallery(cat_dir)
        except Exception as exc:
            print(f'gallery generation failed for {cat_dir.name}: {type(exc).__name__}: {exc}')
    # 资源/文件页（build_view 会清空视图目录，必须一并重建）
    try:
        from .resource_view import write_resource_pages
        from .store import Store
        resource_counts = write_resource_pages(view, Store(project_dir / 'data' / 'bot.db'))
        counts.update(resource_counts)
    except Exception as exc:
        print(f'resource pages failed: {type(exc).__name__}: {exc}')
    readme = view / 'README.txt'
    readme.write_text(
        '这是图片分类视图，按数据库筛选结果生成。\n'
        '优先使用 NTFS 硬链接，通常不额外占空间；不要在这里编辑原始数据库。\n\n'
        '分类：\n'
        '01_AI元数据_*：图片本身带 ComfyUI/NovelAI 等元数据，可信度最高。\n'
        '02_群友好评：被引用/附近好评、求提示词等晋升。\n'
        '03_AI上下文：图片附近有提示词/模型/工作流/参数讨论。\n'
        '04_候选待观察：暂存，等待后续反馈。\n'
        '05_小番茄混淆：经 Gilbert 曲线逆置换验证的混淆图（算法级确认）。\n'
        '05_小番茄混淆_压缩：重压/缩放后的混淆图（弱信号，逆置换无法完全还原）。\n'
        '99_普通无元数据：正常图片但无 AI 元数据。\n',
        encoding='utf-8',
    )
    write_view_index(view, counts)
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

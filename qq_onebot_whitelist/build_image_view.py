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

CATEGORY_NAMES = {
    'ai_metadata': '01_AI元数据',
    'positive_feedback': '02_群友好评',
    'prompt_bound': '03_提示词绑定',
    'params_discussion': '03_参数讨论',
    'candidate': '04_候选待观察',
    'xiaofanqie_obfuscated': '05_小番茄混淆',
    'xiaofanqie_compressed': '05_小番茄混淆_压缩',
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
    mask_html = (
        '<label style="display:inline-flex;align-items:center;gap:6px;margin-bottom:14px;cursor:pointer">'
        '<input type="checkbox" id="maskRestored" checked> 遮罩混淆还原图（默认模糊，点击图片显示）</label>'
        '<script>'
        'const maskBox=document.getElementById("maskRestored");'
        'try{maskBox.checked=localStorage.getItem("maskRestored")!=="0";}catch(e){}'
        'maskBox.addEventListener("change",()=>{try{localStorage.setItem("maskRestored",maskBox.checked?"1":"0");}catch(e){}});'
        '</script>'
    )
    collapse_html = (
        '<label style="display:inline-flex;align-items:center;gap:6px;margin:0 0 14px 18px;cursor:pointer">'
        '<input type="checkbox" id="collapseBatches" checked> 01 同批折叠（同一工作流的图合并）</label>'
        '<script>'
        'const cb=document.getElementById("collapseBatches");'
        'try{cb.checked=localStorage.getItem("collapseBatches")!=="0";}catch(e){}'
        'cb.addEventListener("change",()=>{try{localStorage.setItem("collapseBatches",cb.checked?"1":"0");}catch(e){}});'
        '</script>'
    )
    doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>QQ AI 图片视图</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:24px;background:#101114;color:#eee}
a{color:#8ab4ff;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.card{padding:18px;background:#181a20;border:1px solid #2b2f3a;border-radius:14px}.muted{color:#aaa}
</style><body><h1>QQ AI 图片视图</h1>
''' + mask_html + collapse_html + '''
<p class="muted">分类视图入口；03_提示词绑定 有专门 HTML 页面，其它分类可直接浏览目录图片。</p>
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
    """为图片分类目录生成单页图库（全部图片 + 跳转/回顶 + 同批折叠角标）。"""
    if (cat_dir / 'index.html').exists():
        return  # 已有专门页面（如 03_提示词绑定）则不覆盖
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    def image_id(p: Path) -> int:
        try:
            return int(p.stem.split('_')[0].lstrip('#'))
        except (ValueError, IndexError):
            return 0
    images = sorted(
        (p for p in cat_dir.rglob('*') if p.is_file() and p.suffix.lower() in image_exts),
        key=lambda p: image_id(p),
        reverse=True,
    )
    if not images:
        return
    cells = ''
    for p in images:
        r = os.path.relpath(p, cat_dir).replace(os.sep, '/')
        mask_attr = ' data-masked="1"' if '还原' in p.name else ''
        cells += (
            f'<a class="cell"{mask_attr} href="{url_path(r)}">'
            f'<img loading="lazy" src="{url_path(r)}" alt=""></a>'
        )
    doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{title}</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#0d0f13;color:#eef1f6}}
header{{padding:18px 22px;position:sticky;top:0;background:#0d0f13ee;backdrop-filter:blur(8px);z-index:2;border-bottom:1px solid #262d3a}}
h1{{font-size:18px;margin:0 0 4px}}
.muted{{color:#8b96a8;font-size:13px}}
#back{{color:#8ab4ff;text-decoration:none;font-size:13px;margin-right:14px}}
.toolbar{{display:flex;align-items:center;gap:12px;padding:6px 22px 8px;font-size:13px}}
#jumpTo{{width:90px;padding:4px 8px;border-radius:6px;border:1px solid #343a46;background:#171a21;color:#fff}}
#topBtn,#expandAll,#collapseAll{{padding:4px 12px;border-radius:6px;border:1px solid #343a46;background:#171a21;color:#9fc2ff;cursor:pointer}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;padding:16px 22px}}
.cell{{display:block;border-radius:8px;overflow:hidden;background:#171b23}}
.cell img{{width:100%;height:180px;object-fit:cover;display:block}}
#overlay{{display:none;position:fixed;inset:0;background:#000d;z-index:10;align-items:center;justify-content:center;cursor:zoom-out}}
#overlay img{{max-width:92vw;max-height:92vh;border-radius:6px}}
</style></head><body>
<header><a id="back" href="../index.html">← 返回</a><h1>{title}</h1><div class="muted">{count} 张</div>
<div class="toolbar">
  <span class="muted">共 {count} 张</span>
  <input id="jumpTo" type="number" min="1" max="{count}" placeholder="跳转">
  <button id="topBtn">回顶部</button>
  <button id="expandAll">展开全部同批</button>
  <button id="collapseAll">恢复折叠</button>
  <span id="collapseInfo" class="muted"></span>
</div>
</header>
<div class="grid">{cells}</div>
<div id="overlay"><img id="lightbox" src=""></div>
<script>
const cells=[...document.querySelectorAll('.cell')];const overlay=document.getElementById('overlay');const img=document.getElementById('lightbox');let cur=0;
let masked=true;try{{masked=localStorage.getItem("maskRestored")!=="0";}}catch(e){{}}
cells.forEach(a=>{{if(masked&&a.dataset.masked==='1'){{const im=a.querySelector('img');im.style.filter='blur(14px)';}}}});
const collapse=localStorage.getItem("collapseBatches")!=="0";
if(collapse){{const groups={{}};cells.forEach(a=>{{const m=(a.getAttribute('href')||'').match(/_pk([0-9a-f]{{8}})/);if(m){{const k=m[1];(groups[k]=groups[k]||[]).push(a);}}}});let folded=0;Object.values(groups).forEach(g=>{{if(g.length>1&&g.length<=30){{folded++;g.forEach((a,i)=>{{if(i>0){{a.style.display='none';}}}});const b=document.createElement('span');b.textContent='同批 '+g.length+' 张';b.style.cssText='position:absolute;top:6px;left:6px;background:#000c;color:#ffd98a;font-size:12px;padding:2px 8px;border-radius:999px;cursor:pointer;z-index:2';g[0].style.position='relative';g[0].appendChild(b);b.addEventListener('click',e=>{{e.preventDefault();e.stopPropagation();g.forEach(a=>{{a.style.display='';}});b.remove();}});}}}});const ci=document.getElementById('collapseInfo');if(ci&&folded){{ci.textContent='已折叠 '+folded+' 组同批（≤30 张），点角标展开';}}}}
const jump=document.getElementById('jumpTo');jump.addEventListener('keydown',e=>{{if(e.key==='Enter'){{const n=parseInt(jump.value,10);if(n>0&&n<=cells.length){{cells[n-1].scrollIntoView({{block:'center'}});}}}}}});
document.getElementById('topBtn').addEventListener('click',()=>window.scrollTo({{top:0,behavior:'smooth'}}));
document.getElementById('expandAll').addEventListener('click',()=>{{try{{localStorage.setItem('collapseBatches','0');}}catch(e){{}}location.reload();}});
document.getElementById('collapseAll').addEventListener('click',()=>{{try{{localStorage.setItem('collapseBatches','1');}}catch(e){{}}location.reload();}});
function show(i){{cur=(i+cells.length)%cells.length;img.src=cells[cur].href;overlay.style.display='flex';}}
cells.forEach((a,i)=>a.addEventListener('click',e=>{{e.preventDefault();if(a.dataset.masked==='1'){{const im=a.querySelector('img');im.style.filter='none';delete a.dataset.masked;return;}}show(i);}}));
overlay.addEventListener('click',e=>{{if(e.target===overlay)overlay.style.display='none';}});
document.addEventListener('keydown',e=>{{if(overlay.style.display==='flex'){{if(e.key==='Escape')overlay.style.display='none';if(e.key==='ArrowLeft')show(cur-1);if(e.key==='ArrowRight')show(cur+1);}}}});
</script></body></html>'''
    (cat_dir / 'index.html').write_text(doc.format(
        title=html.escape(cat_dir.name),
        count=len(images),
        cells=cells,
    ), encoding='utf-8')


def _write_context_gallery(cat_dir: Path, items: list[dict[str, object]], title: str) -> None:
    """03 上下文分类：图片 + 绑定文本（提示词/参数讨论）成对卡片（单页全部）。"""
    template = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                '<title>{title}</title><style>'
                'body{{font-family:system-ui,sans-serif;margin:22px;background:#0d0f13;color:#eef1f6}}'
                '.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}'
                '.card{{background:#171a21;border:1px solid #2b313d;border-radius:12px;padding:10px}}'
                '.card img{{width:100%;max-height:60vh;object-fit:contain;background:#000;border-radius:8px}}'
                'a{{color:#9fc2ff}}.muted{{color:#aab2c0}}</style></head><body>'
                '<h1>{title}</h1><div class="cards">{cards}</div></body></html>')
    cat_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for item in items:
        url = url_path(str(item['image_rel']))
        mask_attr = ' class="masked-card"' if item.get('deobfuscated') else ''
        cards.append(
            '<article class="card">'
            f'<a href="{url}"{mask_attr}><img src="{url}" loading="lazy"></a>'
            f'<p class="muted">#{html.escape(str(item["id"]))} · {html.escape(str(item["meta"]))}</p>'
                f'<pre style="white-space:pre-wrap;background:#151922;padding:10px;border-radius:8px">'
                f'{html.escape(str(item.get("text") or ""))}</pre>'
            '</article>'
        )
    mask_script = (
        '<script>'
        'try{const m=localStorage.getItem("maskRestored")!=="0";'
        'if(m){document.querySelectorAll("a.masked-card").forEach(a=>{'
        'a.querySelector("img").style.filter="blur(14px)";'
        'a.addEventListener("click",e=>{e.preventDefault();'
        'a.querySelector("img").style.filter="none";a.classList.remove("masked-card");});});}'
        '}catch(e){}'
        '</script>'
    )
    (cat_dir / 'index.html').write_text(
        template.format(title=html.escape(title), cards=''.join(cards)) + mask_script,
        encoding='utf-8',
    )


def write_prompt_bound_gallery(cat_dir: Path, items: list[dict[str, object]]) -> None:
    _write_context_gallery(cat_dir, items, '03 提示词绑定')


def write_params_gallery(cat_dir: Path, items: list[dict[str, object]]) -> None:
    _write_context_gallery(cat_dir, items, '03 参数讨论')


def build_view(project_dir: Path) -> dict[str, int]:
    db = project_dir / 'data' / 'bot.db'
    view = project_dir / 'data' / 'view'
    if view.exists():
        shutil.rmtree(view)
    view.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    image_cols = {row[1] for row in conn.execute('PRAGMA table_info(images)')}
    sha256_col = 'sha256, ' if 'sha256' in image_cols else ''
    restored_col = 'restored_path, ' if 'restored_path' in image_cols else ''
    deobfuscated_col = 'deobfuscated, ' if 'deobfuscated' in image_cols else ''
    binding_cols = 'bound_prompt, prompt_key, context_reason, ' if 'bound_prompt' in image_cols else ''
    rows = conn.execute(
        '''SELECT id, ''' + sha256_col + '''scope, user_id, seen_at, format, width, height, size, has_ai_metadata, ai_source, retention_reason, kept_path, ''' + restored_col + deobfuscated_col + binding_cols + '''text_excerpt, raw_json
           FROM images WHERE kept_path IS NOT NULL ORDER BY retention_reason, id DESC'''
    ).fetchall()
    group_names = group_name_map_from_conn(conn)
    counts: dict[str, int] = {}
    prompt_bound_items: list[dict[str, object]] = []
    params_items: list[dict[str, object]] = []
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
        dst = view / cat / size_class / filename
        mode = make_link_or_copy(src, dst)
        counts[cat] = counts.get(cat, 0) + 1
        if reason in ('prompt_bound', 'params_discussion'):
            image_rel = os.path.relpath(dst, view / cat).replace(os.sep, '/')
            target_items = prompt_bound_items if reason == 'prompt_bound' else params_items
            target_items.append({
                'id': str(row['id']),
                'image_rel': image_rel,
                'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                'text': str(row['bound_prompt'] or ''),
                'deobfuscated': is_deobfuscated,
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
                ctx_dst = view / context_cat / size_class / ctx_filename
                make_link_or_copy(src, ctx_dst)
                counts[context_cat] = counts.get(context_cat, 0) + 1
                if context_reason == 'prompt_bound':
                    ctx_rel = os.path.relpath(ctx_dst, view / context_cat).replace(os.sep, '/')
                    prompt_bound_items.append({
                        'id': str(row['id']),
                        'image_rel': ctx_rel,
                        'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                        'text': str(row['bound_prompt'] or ''),
                        'deobfuscated': True,
                    })
                elif context_reason == 'params_discussion':
                    ctx_rel = os.path.relpath(ctx_dst, view / context_cat).replace(os.sep, '/')
                    params_items.append({
                        'id': str(row['id']),
                        'image_rel': ctx_rel,
                        'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                        'text': str(row['bound_prompt'] or ''),
                        'deobfuscated': True,
                    })
    if prompt_bound_items:
        write_prompt_bound_gallery(view / CATEGORY_NAMES['prompt_bound'], prompt_bound_items)
    if params_items:
        write_params_gallery(view / CATEGORY_NAMES['params_discussion'], params_items)
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
    readme.write_text(
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

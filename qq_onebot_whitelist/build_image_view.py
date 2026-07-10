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

from .scope_names import display_scope
from .content_utils import redact_secrets
from .html_render import render_markdown

CATEGORY_NAMES = {
    'ai_metadata': '01_AI元数据',
    'positive_feedback': '02_群友好评',
    'nearby_ai_context': '03_AI上下文',
    'candidate': '04_候选待观察',
    'no_ai_metadata': '99_普通无元数据',
}


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


def context_summary(conn: sqlite3.Connection, scope: str, message_db_id: int | None = None) -> str:
    try:
        row = None
        if message_db_id is not None:
            row = conn.execute(
                '''SELECT summary FROM ai_context_batches
                   WHERE scope = ? AND start_message_id <= ? AND end_message_id >= ?
                   ORDER BY id DESC LIMIT 1''',
                (scope, message_db_id, message_db_id),
            ).fetchone()
        if row:
            return redact_secrets(str(row['summary'] or ''))
        row = conn.execute(
            'SELECT summary FROM ai_context_batches WHERE scope = ? ORDER BY id DESC LIMIT 1',
            (scope,),
        ).fetchone()
    except sqlite3.OperationalError:
        return ''
    return redact_secrets(str(row['summary'] if row and row['summary'] else ''))


def write_context_html(context_dir: Path, items: list[dict[str, str]]) -> None:
    cards = []
    if not items:
        cards.append('<article class="card"><div><h2>当前没有仍存在的 03_AI上下文 图片</h2><p class="muted">旧记录的源图可能已被预算/候选清理；后续新保存的上下文图会出现在这里。</p></div></article>')
    for item in items:
        summary_html = render_markdown(item['summary'] or '暂无批摘要')
        cards.append(
            '<article class="card">'
            f'<div class="image-pane"><a href="{html.escape(url_path(item["image_rel"]))}"><img src="{html.escape(url_path(item["image_rel"]))}" loading="lazy"></a></div>'
            f'<div class="content"><h2>#{html.escape(item["id"])} · {html.escape(item["scope"])}</h2>'
            f'<p class="muted">{html.escape(item["meta"])}</p>'
            f'<h3>批次摘要</h3><div class="markdown">{summary_html}</div>'
            f'<details><summary>查看图片附近原始上下文</summary><pre>{html.escape(redact_secrets(item["text_excerpt"] or "无"))}</pre></details>'
            '</div></article>'
        )
    doc = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>03_AI上下文</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1440px;margin:0 auto;padding:24px;background:#0d0f13;color:#eef1f6}
h1{font-size:26px}.card{display:grid;grid-template-columns:minmax(240px,380px) minmax(0,1fr);gap:24px;padding:20px;margin:20px 0;background:#171a21;border:1px solid #2b313d;border-radius:16px}.image-pane{align-self:start;position:sticky;top:18px}
img{width:100%;max-height:70vh;object-fit:contain;border-radius:12px;background:#000}.muted{color:#aab2c0}.markdown{line-height:1.65;background:#11141a;padding:16px 20px;border-radius:12px;overflow-wrap:anywhere}.markdown h2,.markdown h3{margin-top:1.25em}.markdown pre,details pre{white-space:pre-wrap;overflow:auto;background:#090b0f;padding:12px;border-radius:9px}.markdown code{background:#272d38;padding:.12em .35em;border-radius:4px}.markdown table{border-collapse:collapse;width:100%}.markdown th,.markdown td{border:1px solid #394150;padding:8px;text-align:left}.table-wrap{overflow:auto}.markdown blockquote{margin:1em 0;padding:.2em 1em;border-left:4px solid #668bc4;color:#c7cfdb}details{margin-top:18px}summary{cursor:pointer;color:#9fc2ff}
@media(max-width:820px){body{padding:14px}.card{grid-template-columns:1fr;padding:14px}.image-pane{position:static}}
</style><body><h1>03_AI上下文</h1>
<p class="muted">摘要已渲染 Markdown；原始附近上下文默认折叠，并统一脱敏。</p>
''' + '\n'.join(cards) + '</body></html>'
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / 'index.html').write_text(doc, encoding='utf-8')


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


def build_view(project_dir: Path) -> dict[str, int]:
    db = project_dir / 'data' / 'bot.db'
    view = project_dir / 'data' / 'view'
    if view.exists():
        shutil.rmtree(view)
    view.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        '''SELECT id, scope, user_id, seen_at, format, width, height, size, has_ai_metadata, ai_source, retention_reason, kept_path, text_excerpt, raw_json
           FROM images WHERE kept_path IS NOT NULL ORDER BY retention_reason, id DESC'''
    ).fetchall()
    group_names = group_name_map_from_conn(conn)
    counts: dict[str, int] = {}
    context_items: list[dict[str, str]] = []
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
        if reason == 'nearby_ai_context':
            try:
                raw = json.loads(row['raw_json'] or '{}')
                message_db_id = int(raw['message_db_id']) if raw.get('message_db_id') is not None else None
            except Exception:
                message_db_id = None
            image_rel = os.path.relpath(dst, view / cat).replace(os.sep, '/')
            context_items.append({
                'id': str(row['id']),
                'scope': display_scope(str(row['scope'] or ''), group_names),
                'image_rel': image_rel,
                'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                'text_excerpt': str(row['text_excerpt'] or ''),
                'summary': context_summary(conn, str(row['scope'] or ''), message_db_id),
            })
    write_context_html(view / CATEGORY_NAMES['nearby_ai_context'], context_items)
    conn.close()
    readme = view / 'README.txt'
    readme.write_text(
        '这是图片分类视图，按数据库筛选结果生成。\n'
        '优先使用 NTFS 硬链接，通常不额外占空间；不要在这里编辑原始数据库。\n\n'
        '分类：\n'
        '01_AI元数据_*：图片本身带 ComfyUI/NovelAI 等元数据，可信度最高。\n'
        '02_群友好评：被引用/附近好评、求提示词等晋升。\n'
        '03_AI上下文：图片附近有提示词/模型/工作流/参数讨论。\n'
        '04_候选待观察：暂存，等待后续反馈。\n',
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

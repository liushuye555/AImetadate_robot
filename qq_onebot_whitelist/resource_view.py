from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import html
from urllib.parse import urlparse

from .content_utils import fallback_link_description, file_description, redact_secrets, resource_context
from .daily_report import canonical_url, dedupe_url_key, format_size, is_low_value_link, link_purpose, link_score
from .scope_names import display_scope


def _html_page(title: str, intro: str, sections: list[str]) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        f'<title>{html.escape(title)}</title>'
        '<style>:root{color-scheme:dark}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1180px;margin:0 auto;padding:28px;background:#0d0f13;color:#eef1f6}'
        'a{color:#8ab4ff;text-decoration:none}a:hover{text-decoration:underline}.toolbar{position:sticky;top:0;padding:12px 0;background:#0d0f13ee;backdrop-filter:blur(8px);z-index:2}'
        'input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid #343a46;background:#171a21;color:#fff;font-size:16px}.card{padding:18px;margin:16px 0;background:#171a21;border:1px solid #2b313d;border-radius:14px}'
        '.muted{color:#aab2c0}.resource-list{list-style:none;margin:0;padding:0}.resource-item{padding:14px 0;border-top:1px solid #292f3a;line-height:1.55}.resource-item:first-child{border-top:0}.title{font-size:16px;font-weight:650;overflow-wrap:anywhere}.desc{margin:.35em 0;color:#d5dae3}.meta{font-size:13px;color:#929cab}.badge{display:inline-block;padding:2px 8px;margin-right:7px;border-radius:999px;background:#27344d;color:#b9d3ff;font-size:12px}.url{font-size:13px;overflow-wrap:anywhere}@media(max-width:700px){body{padding:16px}.card{padding:14px}}</style>'
        f'<body><h1>{html.escape(title)}</h1><p class="muted">{html.escape(intro)}</p><div class="toolbar"><input id="filter" placeholder="搜索群名、文件名、简介或网址"></div>'
        + '\n'.join(sections)
        + '<script>const q=document.getElementById("filter");q.addEventListener("input",()=>{const v=q.value.trim().toLowerCase();document.querySelectorAll(".resource-item").forEach(x=>x.hidden=v&&!x.textContent.toLowerCase().includes(v));document.querySelectorAll("section.card").forEach(s=>s.hidden=!s.querySelector(".resource-item:not([hidden])"));});</script></body></html>'
    )


def select_resource_links(store, *, limit: int = 10000) -> dict[str, list[dict]]:
    selected: dict[str, dict] = {}
    for item in store.recent_link_records(limit=limit):
        url = str(item.get('url') or '')
        context = str(item.get('message_text') or item.get('quoted_text') or '')
        if not url or is_low_value_link(url, context):
            continue
        score = link_score(item)
        if score <= 0:
            continue
        key = dedupe_url_key(url)
        old = selected.get(key)
        if old is None or score > int(old.get('_score') or 0):
            selected[key] = {**item, 'url': canonical_url(url), 'purpose': link_purpose(item) or '值得一看', '_score': score}
    by_scope: dict[str, list[dict]] = defaultdict(list)
    for item in sorted(selected.values(), key=lambda x: (str(x.get('scope') or ''), -int(x.get('_score') or 0), str(x.get('url') or ''))):
        by_scope[str(item.get('scope') or 'unknown')].append(item)
    return dict(by_scope)


def select_resource_files(store, *, limit: int = 10000) -> dict[str, list[dict]]:
    seen: dict[tuple[str, str, int | None, str], dict] = {}
    for item in store.recent_files(limit=limit):
        name = str(item.get('file_name') or '').strip()
        if not name:
            continue
        kind = str(item.get('kind') or 'file')
        key = (name.lower(), item.get('file_size'), kind)
        seen.setdefault(key, item)
    by_scope: dict[str, list[dict]] = defaultdict(list)
    for item in seen.values():
        by_scope[str(item.get('scope') or 'unknown')].append(item)
    for items in by_scope.values():
        items.sort(key=lambda x: (str(x.get('kind') or ''), str(x.get('file_name') or '').lower()))
    return dict(by_scope)


def write_resource_pages(view: str | Path, store) -> dict[str, int]:
    view = Path(view)
    view.mkdir(parents=True, exist_ok=True)

    group_names = store.group_name_map()
    links_by_scope = select_resource_links(store)
    link_sections: list[str] = []
    link_count = 0
    for scope, items in sorted(links_by_scope.items()):
        link_count += len(items)
        label = display_scope(scope, group_names)
        link_sections.append(f'<section class="card"><h2>{html.escape(label)} <span class="muted">{len(items)} 条</span></h2><ul class="resource-list">')
        for item in items:
            url = str(item.get('url') or '')
            purpose_text = str(item.get('purpose') or '值得一看')
            description = resource_context(str(item.get('message_text') or item.get('quoted_text') or ''), url) or fallback_link_description(url, purpose_text)
            host = urlparse(url).netloc.lower()
            link_sections.append(
                '<li><article class="resource-item">'
                f'<div class="title"><span class="badge">用途：{html.escape(purpose_text)}</span>{html.escape(host or url)}</div>'
                f'<p class="desc">{html.escape(description)}</p>'
                f'<a class="url" href="{html.escape(url)}">{html.escape(url)}</a>'
                '</article></li>'
            )
        link_sections.append('</ul></section>')
    if not link_sections:
        link_sections.append('<section class="card"><p class="muted">暂无高价值链接。</p></section>')
    (view / 'resources.html').write_text(
        _html_page('高价值资源链接', '已过滤快手/泛分享；按 URL 去重；按群分类。', link_sections),
        encoding='utf-8',
    )

    files_by_scope = select_resource_files(store)
    file_sections: list[str] = []
    file_count = 0
    for scope, items in sorted(files_by_scope.items()):
        file_count += len(items)
        label = display_scope(scope, group_names)
        file_sections.append(f'<section class="card"><h2>{html.escape(label)} <span class="muted">{len(items)} 个</span></h2><ul class="resource-list">')
        for item in items:
            kind = str(item.get('kind') or 'file')
            name = str(item.get('file_name') or '未命名文件')
            description = resource_context(str(item.get('message_text') or '')) or file_description(name, kind)
            user = html.escape(str(item.get('user_id') or ''))
            file_sections.append(
                '<li><article class="resource-item">'
                f'<div class="title"><span class="badge">{html.escape(kind)}</span>{html.escape(redact_secrets(name))}</div>'
                f'<p class="desc">{html.escape(description)}</p>'
                f'<div class="meta">{html.escape(format_size(item.get("file_size")))} · user:{user}</div>'
                '</article></li>'
            )
        file_sections.append('</ul></section>')
    if not file_sections:
        file_sections.append('<section class="card"><p class="muted">暂无高价值文件/工作流。</p></section>')
    (view / 'files.html').write_text(
        _html_page('高价值文件/工作流', '按群分类，按 文件名+大小+类型 去重；不展示长下载 URL。', file_sections),
        encoding='utf-8',
    )

    return {'resource_links': link_count, 'resource_files': file_count}

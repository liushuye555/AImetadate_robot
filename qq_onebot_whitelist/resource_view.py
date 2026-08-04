from __future__ import annotations

from pathlib import Path
import html
from urllib.parse import urlparse

from .content_utils import fallback_link_description, file_description, redact_secrets, resource_context
from .daily_report import canonical_url, dedupe_url_key, format_size, is_low_value_link, link_purpose, link_score
from .scope_names import display_scope
from .llm_link_judge import cost_log, llm_judge_link
from .resources import deterministic_category, domain_profiles, is_local_link, link_category, site_key


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


def select_resource_links(store, *, limit: int = 10000, mode: str = 'rule') -> list[dict]:
    """筛选高价值链接。mode=llm/both 时，规则/站点记忆判不出的链接交给 LLM 复核（按 URL 缓存）。"""
    from .daily_report import canonical_url, link_purpose
    selected: dict[str, dict] = {}
    profiles = domain_profiles(store, limit=limit)
    for item in store.recent_link_records(limit=limit):
        url = str(item.get('url') or '')
        context = str(item.get('message_text') or item.get('quoted_text') or '')
        if not url:
            continue
        if is_local_link(url):
            continue  # 本地/内网链接他人无法访问，不作为资源展示
        key = dedupe_url_key(url)
        det = deterministic_category(profiles.get(site_key(urlparse(url).netloc)))
        purpose = link_purpose(item) or ''
        low_value = is_low_value_link(url, context)
        metadata = store.get_link_metadata(key) or {}
        title = str(metadata.get('title') or '')
        desc = str(metadata.get('description') or '')
        # 站点记忆：确定站点不调 LLM；多功能站点规则判不出时先交给 LLM 挽救
        if mode != 'rule' and (low_value or not purpose) and not det:
            cached = store.get_link_judge(key)
            if cached is None:
                judge_purpose, tokens = llm_judge_link(url, context)
                cost_log["calls"] += 1
                cost_log["total_tokens"] += int(tokens or 0)
                store.set_link_judge(key, judge_purpose)
                cached = judge_purpose
            if cached:
                purpose = cached
                low_value = False
        # 站点记忆：确定站点低价值挽救 + 用途兜底
        if low_value and not (det and det not in ('娱乐视频', '其他')):
            continue
        if not purpose and det:
            purpose = '值得一看'
        if low_value:
            continue
        item = {**item, 'purpose': purpose, 'title': title,
                'profile': profiles.get(site_key(urlparse(url).netloc)) or {}, 'det': det or ''}
        item['category'] = link_category(url, f"{context} {title} {desc}".strip())
        if item['category'] == '其他' and det:
            item['category'] = det  # 站点记忆兜底，避免落入"其他"
        if purpose == '核心AI资源' and item['category'] == '其他':
            item['category'] = 'AI资源'  # 核心AI资源兜底，绝不落"其他"
        score = link_score(item)
        old = selected.get(key)
        if old is None or score > int(old.get('_score') or 0):
            selected[key] = {**item, 'url': canonical_url(url), 'purpose': purpose or '值得一看', '_score': score}
    return sorted(selected.values(), key=lambda x: (-int(x.get('_score') or 0), str(x.get('url') or '')))


def select_resource_files(store, *, limit: int = 10000) -> list[dict]:
    seen: dict[tuple[str, int | None, str], dict] = {}
    for item in store.recent_files(limit=limit):
        name = str(item.get('file_name') or '').strip()
        if not name:
            continue
        kind = str(item.get('kind') or 'file')
        key = (name.lower(), item.get('file_size'), kind)
        if key not in seen:
            seen[key] = {**item, 'scopes': []}
        scope = str(item.get('scope') or 'unknown')
        if scope not in seen[key]['scopes']:
            seen[key]['scopes'].append(scope)
    return sorted(seen.values(), key=lambda x: (str(x.get('kind') or ''), str(x.get('file_name') or '').lower()))


def write_resource_pages(view: str | Path, store, *, link_judge_mode: str = 'rule') -> dict[str, int]:
    view = Path(view)
    view.mkdir(parents=True, exist_ok=True)

    group_names = store.group_name_map()
    links = select_resource_links(store, mode=link_judge_mode)
    link_sections: list[str] = []
    link_count = len(links)
    grouped: dict[str, list[dict]] = {}
    for item in links:
        grouped.setdefault(str(item.get('category') or '其他'), []).append(item)
    CATEGORY_ORDER = [
        'AI模型', 'AI工作流', 'AI工具插件', 'AI在线服务', 'AI数据集', 'AI资源',
        '教程', '教程视频', '图片', '音乐', '导航', '娱乐视频', '新闻', '其他',
    ]
    ordered = [(c, grouped[c]) for c in CATEGORY_ORDER if c in grouped]
    for c, items in grouped.items():
        if c not in CATEGORY_ORDER:
            ordered.append((c, items))
    link_sections.append(
        '<div class="toolbar"><style>.pf{padding:6px 14px;border-radius:8px;border:1px solid #343a46;background:#171a21;color:#9fc2ff;cursor:pointer;margin-right:8px}.pf.active{background:#27344d;color:#fff}</style>'
        '<span class="muted">共 ' + str(link_count) + ' 条</span>'
        '<button class="pf active" data-pf="">全部</button>'
        + ''.join(f'<button class="pf" data-pf="{c}">{c}</button>' for c, _ in ordered)
        + '</div>'
    )
    for category, items in ordered:
        link_sections.append(
            f'<section class="card"><h2>{html.escape(category)} '
            f'<span class="muted">{len(items)} 条</span></h2><ul class="resource-list">'
        )
        for item in items:
            url = str(item.get('url') or '')
            purpose_text = str(item.get('purpose') or '链接')
            description = resource_context(str(item.get('message_text') or item.get('quoted_text') or ''), url) \
                or fallback_link_description(url, purpose_text)
            host = urlparse(url).netloc.lower()
            title = str(item.get('title') or '').strip()
            seen = str(item.get('seen_at') or '')[:10]
            scope = str(item.get('scope') or '')
            scope_name = display_scope(scope, group_names)
            if scope.startswith('group:') and scope_name == scope:
                scope_name = '未知群'
            headline = f'{html.escape(title)}<div class="muted">{html.escape(host or url)}</div>' if title else html.escape(host or url)
            det = str(item.get('det') or '')
            profile = item.get('profile') or {}
            memory_badge = '<span class="badge">站点记忆</span>' if det else ''
            profile_line = ''
            if profile:
                funcs = ' · '.join(
                    f'{html.escape(k)}×{v}' for k, v in sorted(profile.items(), key=lambda kv: -kv[1])[:5]
                )
                profile_line = f'<div class="meta">该站历史功能：{funcs}</div>'
            link_sections.append(
                '<li><article class="resource-item" data-purpose="' + html.escape(category) + '">'
                f'<div class="title"><span class="badge">用途：{html.escape(purpose_text)}</span>{memory_badge}{headline}</div>'
                f'<p class="desc">{html.escape(description)}</p>'
                f'<a class="url" href="{html.escape(url)}">{html.escape(url)}</a>'
                f'<div class="meta">{html.escape(scope_name)} · {html.escape(seen)}</div>'
                + profile_line +
                '</article></li>'
            )
        link_sections.append('</ul></section>')
    link_sections.append(
        '<script>'
        'const pfs=[...document.querySelectorAll("button.pf")];'
        'const items=[...document.querySelectorAll(".resource-item")];'
        'pfs.forEach(b=>b.addEventListener("click",()=>{'
        'pfs.forEach(x=>x.classList.remove("active"));b.classList.add("active");'
        'const p=b.dataset.pf;'
        'items.forEach(x=>x.hidden=!!(p&&x.dataset.purpose!==p));'
        'document.querySelectorAll("section.card").forEach(s=>s.hidden=!s.querySelector(".resource-item:not([hidden])"));'
        '}));'
        '</script>'
    )
    if not link_sections:
        link_sections.append('<section class="card"><p class="muted">暂无高价值链接。</p></section>')
    (view / 'resources.html').write_text(
        _html_page('资源链接', '仅过滤明确的娱乐、广告和泛分享链接；按 URL 去重。', link_sections),
        encoding='utf-8',
    )

    files = select_resource_files(store)
    file_sections: list[str] = []
    file_count = len(files)
    if files:
        file_sections.append(f'<section class="card"><h2>群文件 <span class="muted">{len(files)} 个</span></h2><ul class="resource-list">')
    for item in files:
        kind = str(item.get('kind') or 'file')
        name = str(item.get('file_name') or '未命名文件')
        description = resource_context(str(item.get('message_text') or '')) or file_description(name, kind)
        groups = '、'.join(display_scope(scope, group_names) for scope in item.get('scopes') or [])
        file_sections.append(
            '<li><article class="resource-item">'
            f'<div class="title"><span class="badge">{html.escape(kind)}</span>{html.escape(redact_secrets(name))}</div>'
            f'<p class="desc">{html.escape(description)}</p>'
            f'<div class="meta">{html.escape(format_size(item.get("file_size")))} · {html.escape(groups)}</div>'
            '</article></li>'
        )
    if files:
        file_sections.append('</ul></section>')
    if not file_sections:
        file_sections.append('<section class="card"><p class="muted">暂无高价值文件/工作流。</p></section>')
    (view / 'files.html').write_text(
        _html_page('群文件/工作流', '按 文件名+大小+类型 去重；文件不下载，只记录所在群。', file_sections),
        encoding='utf-8',
    )

    return {'resource_links': link_count, 'resource_files': file_count}

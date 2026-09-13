from __future__ import annotations

from pathlib import Path
import html
from urllib.parse import urlparse

from .content_utils import fallback_link_description, file_description, redact_secrets, resource_context
from .daily_report import canonical_url, dedupe_url_key, format_size, is_low_value_link, link_purpose, link_score
from .scope_names import display_scope
from .llm_link_judge import cost_log, llm_judge_link
from .resources import (deterministic_category, domain_profiles, is_direct_image_link, is_local_link,
                        is_unresolved_short_link, link_category, nearest_link_context, site_key)


def _html_page(title: str, intro: str, sections: list[str], *, toolbar: str = '',
               background: str = '', sort_options: list[tuple[str, str]] | None = None) -> str:
    from .view_theme import page_shell

    search = ('<div class="search"><input id="filter" type="search" '
              'placeholder="搜索群名、文件名、简介或网址" autocomplete="off"></div>')
    sort_html = ''
    if sort_options:
        opts = ''.join(
            f'<option value="{html.escape(value, quote=True)}">{html.escape(label)}</option>'
            for value, label in sort_options
        )
        sort_html = f'<select id="sortSel" aria-label="排序方式">{opts}</select>'
    body = (
        '<nav class="crumbs"><a href="index.html">← 返回总览</a></nav>'
        f'<h1>{html.escape(title)}</h1><p class="page-desc">{html.escape(intro)}</p>'
        f'<div class="toolbar"><div class="toolbar-inner">{search}{toolbar}{sort_html}</div></div>'
        + '\n'.join(sections)
        + '<div id="noResult">没有匹配的内容，换个关键词试试</div>'
        + _RESOURCE_SCRIPT
    )
    return page_shell(title=title, body=body, background=background)


_RESOURCE_SCRIPT = (
    '<script>'
    'const q=document.getElementById("filter"),items=[...document.querySelectorAll(".resource-item")],'
    'cards=[...document.querySelectorAll("section.card")],count=document.getElementById("count"),'
    'empty=document.getElementById("noResult"),pfs=[...document.querySelectorAll("button.pf")];'
    'const unit=count?(count.dataset.unit||"条"):"条";let activePf="";'
    'function apply(){const v=q.value.trim().toLowerCase();let shown=0;'
    'for(const x of items){const hit=(!activePf||x.dataset.purpose===activePf)&&(!v||x.textContent.toLowerCase().includes(v));'
    'x.hidden=!hit;if(hit)shown++;}'
    'for(const s of cards)s.hidden=!s.querySelector(".resource-item:not([hidden])");'
    'if(count)count.textContent=shown+" "+unit;'
    'if(empty)empty.style.display=shown?"none":"block";}'
    'q.addEventListener("input",apply);'
    'const sortSel=document.getElementById("sortSel"),sorters={'
    '"time-desc":(a,b)=>(b.dataset.time||"").localeCompare(a.dataset.time||""),'
    '"time-asc":(a,b)=>(a.dataset.time||"").localeCompare(b.dataset.time||""),'
    '"name-asc":(a,b)=>(a.dataset.name||"").localeCompare(b.dataset.name||""),'
    '"size-desc":(a,b)=>(parseInt(b.dataset.size||"-1",10)-parseInt(a.dataset.size||"-1",10)),'
    '"size-asc":(a,b)=>(parseInt(a.dataset.size||"-1",10)-parseInt(b.dataset.size||"-1",10))};'
    'if(sortSel){sortSel.addEventListener("change",()=>{const f=sorters[sortSel.value];if(!f)return;'
    'for(const ul of document.querySelectorAll("ul.resource-list")){'
    'const lis=[...ul.children].sort((a,b)=>f(a,b)||0);'
    'for(const li of lis)ul.appendChild(li);}apply();});}'
    'pfs.forEach(b=>b.addEventListener("click",()=>{pfs.forEach(x=>x.classList.remove("active"));'
    'b.classList.add("active");activePf=b.dataset.pf||"";apply();}));'
    'document.querySelectorAll(".copy-link").forEach(b=>b.addEventListener("click",async()=>{const u=b.dataset.url||"";'
    'try{await navigator.clipboard.writeText(u)}catch(e){const t=document.createElement("textarea");t.value=u;'
    'document.body.appendChild(t);t.select();document.execCommand("copy");t.remove()}'
    'const old=b.textContent;b.textContent="已复制";setTimeout(()=>b.textContent=old,1200)}));'
    '</script>'
)


def select_resource_links(store, *, limit: int = 10000, mode: str = 'rule') -> list[dict]:
    """Select useful links using the cached redirect destination when available."""
    selected: dict[str, dict] = {}
    profiles = domain_profiles(store, limit=limit)
    meaningful_categories = {
        'AI模型', 'AI工作流', 'AI工具插件', 'AI在线服务', 'AI中转服务', 'AI数据集', 'AI作品展示',
        '教程', '技术社区', 'AI教程视频', 'AI资讯视频', '音乐视频', '网盘资源',
    }
    for source_item in store.recent_link_records(limit=limit):
        original_url = str(source_item.get('url') or '').strip()
        if not original_url:
            continue
        original_key = dedupe_url_key(original_url)
        metadata = store.get_link_metadata(original_key) or {}
        resolved_url = str(metadata.get('resolved_url') or '').strip()
        # Do not present opaque redirectors until a safe resolver has confirmed their target.
        if is_unresolved_short_link(original_url) and not resolved_url:
            continue
        url = canonical_url(resolved_url or original_url)
        if is_local_link(url) or is_direct_image_link(url):
            continue
        context = nearest_link_context(original_url, str(source_item.get('message_text') or source_item.get('quoted_text') or ''))
        title = str(metadata.get('title') or '').strip()
        desc = str(metadata.get('description') or '').strip()
        category = link_category(url, f'{context} {title} {desc}'.strip())
        item = {**source_item, 'url': url, 'original_url': canonical_url(original_url), 'message_text': context}
        key = dedupe_url_key(url)
        effective_host = site_key(urlparse(url).netloc)
        source_host = site_key(urlparse(original_url).netloc)
        profile = profiles.get(effective_host) or profiles.get(source_host) or {}
        det = deterministic_category(profile)
        purpose = link_purpose(item) or ''
        low_value = is_low_value_link(url, context)
        if mode == 'rule' and category in meaningful_categories:
            low_value = False
        if mode != 'rule' and (low_value or not purpose) and not det:
            cached = store.get_link_judge(key)
            if cached is None:
                judge_purpose, tokens = llm_judge_link(url, context)
                cost_log['calls'] += 1
                cost_log['total_tokens'] += int(tokens or 0)
                store.set_link_judge(key, judge_purpose)
                cached = judge_purpose
            if cached:
                purpose = cached
                low_value = False
        if low_value and not (det and det not in ('娱乐视频', '其他')):
            continue
        if not purpose and (det or category in meaningful_categories):
            purpose = '值得一看'
        if low_value:
            continue
        item = {
            **item,
            'purpose': purpose,
            'title': title,
            'description': desc,
            'profile': profile,
            'det': det or '',
            'category': category if category != '其他' or not det else det,
        }
        if purpose == '核心AI资源' and item['category'] == '其他':
            item['category'] = 'AI资源'
        score = link_score(item)
        old_item = selected.get(key)
        if old_item is None or score > int(old_item.get('_score') or 0):
            selected[key] = {**item, 'purpose': purpose or '值得一看', '_score': score}
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
    from .view_theme import background_css, find_wallpaper

    view = Path(view)
    view.mkdir(parents=True, exist_ok=True)
    background = background_css(find_wallpaper(view))

    group_names = store.group_name_map()
    links = select_resource_links(store, mode=link_judge_mode)
    link_sections: list[str] = []
    link_count = len(links)
    grouped: dict[str, list[dict]] = {}
    for item in links:
        grouped.setdefault(str(item.get('category') or '其他'), []).append(item)
    CATEGORY_ORDER = [
        'AI模型', 'AI工作流', 'AI工具插件', 'AI在线服务', 'AI中转服务', 'AI数据集', 'AI作品展示', 'AI资源', '网盘资源',
        '教程', '技术社区', 'AI教程视频', 'AI资讯视频', '音乐视频', '图片', '音乐', '导航', '娱乐视频', '新闻', '其他',
    ]
    ordered = [(c, grouped[c]) for c in CATEGORY_ORDER if c in grouped]
    for c, items in grouped.items():
        if c not in CATEGORY_ORDER:
            ordered.append((c, items))
    link_toolbar = (
        f'<span id="count" class="chip count-chip" data-unit="条">{link_count} 条</span>'
        '<button type="button" class="pf active" data-pf="">全部</button>'
        + ''.join(f'<button type="button" class="pf" data-pf="{html.escape(c, quote=True)}">{html.escape(c)}</button>' for c, _ in ordered)
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
                or str(item.get('description') or '') or fallback_link_description(url, purpose_text)
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            compact_path = (parsed.path or '/').rstrip('/') or '/'
            if len(compact_path) > 72:
                compact_path = compact_path[:69] + '…'
            title = str(item.get('title') or '').strip()
            seen = str(item.get('seen_at') or '')[:10]
            scope = str(item.get('scope') or '')
            scope_name = display_scope(scope, group_names)
            if scope.startswith('group:') and scope_name == scope:
                scope_name = '未知群'
            headline = html.escape(title) if title else html.escape(host or url)
            endpoint = f'{host}{compact_path}' if host else url
            det = str(item.get('det') or '')
            profile = item.get('profile') or {}
            memory_badge = '<span class="badge">站点记忆</span>' if det else ''
            profile_line = ''
            if profile:
                funcs = ' · '.join(
                    f'{html.escape(k)}×{v}' for k, v in sorted(profile.items(), key=lambda kv: -kv[1])[:5]
                )
                profile_line = f'<div class="meta">该站历史功能：{funcs}</div>'
            escaped_url = html.escape(url, quote=True)
            sort_time = html.escape(str(item.get('seen_at') or '')[:16], quote=True)
            link_sections.append(
                f'<li data-time="{sort_time}"><article class="resource-item" data-purpose="' + html.escape(category) + '">'
                f'<div class="title"><span class="badge">用途：{html.escape(purpose_text)}</span>{memory_badge}{headline}</div>'
                f'<div class="meta">{html.escape(endpoint)}</div>'
                f'<p class="desc">{html.escape(description)}</p>'
                f'<div class="actions"><a href="{escaped_url}" target="_blank" rel="noopener noreferrer">打开链接</a>'
                f'<button type="button" class="copy-link" data-url="{escaped_url}">复制链接</button></div>'
                f'<details class="url"><summary>完整链接</summary><code>{escaped_url}</code></details>'
                f'<div class="meta">{html.escape(scope_name)} · {html.escape(seen)}</div>'
                + profile_line +
                '</article></li>'
            )
        link_sections.append('</ul></section>')
    if not link_sections:
        link_sections.append('<section class="card"><p class="muted">暂无高价值链接。</p></section>')
    (view / 'resources.html').write_text(
        _html_page('资源链接', '仅过滤明确的娱乐、广告和泛分享链接；按 URL 去重。', link_sections,
                   toolbar=link_toolbar, background=background,
                   sort_options=[('', '默认排序'), ('time-desc', '最新优先'), ('time-asc', '最早优先')]),
        encoding='utf-8',
    )

    files = select_resource_files(store)
    file_count = len(files)
    KIND_TITLES = {'workflow': '工作流', 'model': '模型文件', 'archive': '压缩包'}
    file_toolbar = f'<span id="count" class="chip count-chip" data-unit="个">{file_count} 个</span>'
    if files:
        by_kind: dict[str, list[dict]] = {}
        for item in files:
            by_kind.setdefault(str(item.get('kind') or 'other'), []).append(item)
        file_sections: list[str] = []
        for kind, items in sorted(by_kind.items(), key=lambda kv: str(kv[0])):
            title = KIND_TITLES.get(kind, '其他文件')
            file_sections.append(
                f'<section class="card"><h2>{html.escape(title)} '
                f'<span class="muted">{len(items)} 个</span></h2><ul class="resource-list">'
            )
            for item in items:
                name = str(item.get('file_name') or '未命名文件')
                description = resource_context(str(item.get('message_text') or '')) or file_description(name, kind)
                groups = '、'.join(display_scope(scope, group_names) for scope in item.get('scopes') or [])
                sort_time = html.escape(str(item.get('seen_at') or '')[:16], quote=True)
                size_bytes = item.get('file_size')
                size_attr = str(int(size_bytes)) if isinstance(size_bytes, (int, float)) else '-1'
                file_sections.append(
                    f'<li data-time="{sort_time}" data-size="{size_attr}" '
                    f'data-name="{html.escape(name.lower(), quote=True)}"><article class="resource-item">'
                    f'<div class="title"><span class="badge kind">{html.escape(kind)}</span>{html.escape(redact_secrets(name))}</div>'
                    f'<p class="desc">{html.escape(description)}</p>'
                    f'<div class="meta">{html.escape(format_size(item.get("file_size")))} · {html.escape(groups)}</div>'
                    '</article></li>'
                )
            file_sections.append('</ul></section>')
    else:
        file_sections = ['<section class="card"><p class="muted">暂无高价值文件/工作流。</p></section>']
    (view / 'files.html').write_text(
        _html_page('群文件/工作流', '按 文件名+大小+类型 去重；文件不下载，只记录所在群。', file_sections,
                   toolbar=file_toolbar, background=background,
                   sort_options=[('', '默认排序'), ('time-desc', '最新优先'), ('name-asc', '按名称'),
                                 ('size-desc', '最大优先'), ('size-asc', '最小优先')]),
        encoding='utf-8',
    )

    return {'resource_links': link_count, 'resource_files': file_count}

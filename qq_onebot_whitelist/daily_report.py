from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .scope_names import display_scope
from .content_utils import fallback_link_description, file_description, redact_secrets, resource_context


LOW_VALUE_DOMAINS = {
    'v.kuaishou.com',
    'www.kuaishou.com',
    'kuaishou.com',
    'v.douyin.com',
    'www.douyin.com',
}

RESOURCE_DOMAINS = {
    'civitai.com',
    'www.civitai.com',
    'huggingface.co',
    'github.com',
    'www.modelscope.cn',
    'modelscope.cn',
    'www.bilibili.com',
    'bilibili.com',
    'pan.baidu.com',
    'www.123pan.com',
    '123pan.com',
}


def split_message(text: str, *, max_chars: int = 1800) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            chunks.append(rest)
            break
        cut = rest.rfind('\n', 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [x for x in chunks if x]


def format_size(size: int | None) -> str:
    if not size:
        return '未知大小'
    if size >= 1024 * 1024:
        return f'{size / 1024 / 1024:.1f}MB'
    return f'{size / 1024:.1f}KB'


def dedupe_url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip('/') or parsed.path
    # For resource collection, query params are usually tracking/session noise.
    return urlunparse((parsed.scheme.lower() or 'https', host, path, '', '', ''))


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != 'utm' and not k.lower().startswith('utm_')]
    path = parsed.path.rstrip('/') or parsed.path
    return urlunparse((parsed.scheme.lower() or 'https', host, path, '', urlencode(query), ''))


def is_low_value_link(url: str, context: str = '') -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    text = f'{url} {context}'.lower()
    if host in LOW_VALUE_DOMAINS:
        return True
    if '快手极速版' in context or '点击链接，打开' in context:
        return True
    if '番茄酱' in context and '快手' in context:
        return True
    return False


def link_purpose(item: dict) -> str:
    url = str(item.get('url') or '')
    context = str(item.get('message_text') or item.get('quoted_text') or '')
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    text = f'{url} {context}'.lower()
    if host in RESOURCE_DOMAINS or any(token in text for token in ['lora', 'checkpoint', 'comfyui', 'workflow', '工作流', '模型', '提示词', 'civitai', 'huggingface', 'github', '网盘']):
        return '核心AI资源'
    if any(token in text for token in ['工具', '小网站', '网站', 'demo', '在线', '教程', '文档', '试试', '反推', '转换', '下载']):
        return '值得一看'
    return ''


def link_score(item: dict) -> int:
    url = str(item.get('url') or '')
    context = str(item.get('message_text') or item.get('quoted_text') or '')
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    score = 0
    purpose = link_purpose(item)
    if purpose == '核心AI资源':
        score += 3
    elif purpose == '值得一看':
        score += 1
    lowered = f'{url} {context}'.lower()
    for token in ['lora', 'checkpoint', 'comfyui', 'workflow', '工作流', '模型', '提示词', 'civitai', 'huggingface', 'github', '网盘']:
        if token in lowered:
            score += 1
    return score


def describe_file(item: dict) -> str:
    name = str(item.get('file_name') or '未命名文件')
    kind = item.get('kind') or 'file'
    size = format_size(item.get('file_size'))
    return f'[{kind}] {name}（{size}）'


def describe_link_context(item: dict) -> str:
    url = str(item.get('url') or '')
    purpose = str(item.get('purpose') or link_purpose(item) or '值得一看')
    context = resource_context(str(item.get('message_text') or item.get('quoted_text') or ''), url)
    return context or fallback_link_description(url, purpose)


def trim_context(text: str, limit: int = 70) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    return text[:limit] + '…'


def group_items(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[str(item.get('scope') or 'unknown')].append(item)
    return dict(grouped)


def build_daily_resource_report(store, *, limit: int = 300, since: str | None = None, max_per_group: int = 8) -> str | None:
    files = store.recent_files(limit=limit, since=since)
    links = store.recent_link_records(limit=limit, since=since)
    group_names = store.group_name_map() if hasattr(store, 'group_name_map') else {}

    deduped_files: dict[tuple[str, int | None, str], dict] = {}
    for item in files:
        key = (str(item.get('file_name') or '').lower(), item.get('file_size'), str(item.get('kind') or ''))
        deduped_files.setdefault(key, item)

    deduped_links: dict[str, dict] = {}
    for item in links:
        context = str(item.get('message_text') or item.get('quoted_text') or '')
        url = str(item.get('url') or '')
        if not url or is_low_value_link(url, context):
            continue
        score = link_score(item)
        if score <= 0:
            continue
        key = dedupe_url_key(url)
        old = deduped_links.get(key)
        if old is None or score > int(old.get('_score') or 0):
            new_item = dict(item)
            new_item['_score'] = score
            new_item['purpose'] = link_purpose(new_item)
            new_item['canonical_url'] = canonical_url(url)
            deduped_links[key] = new_item

    selected_files = list(deduped_files.values())
    selected_links = sorted(deduped_links.values(), key=lambda x: int(x.get('_score') or 0), reverse=True)
    if not selected_files and not selected_links:
        return None

    scope_count = len({str(x.get('scope')) for x in selected_files + selected_links})
    highlights = [str(item.get('file_name') or '') for item in selected_files[:2]]
    highlights += [describe_link_context(item) for item in selected_links[:2]]
    highlights = [redact_secrets(x) for x in highlights if x]
    lines = [
        'AI 资源增量精选',
        f'简介：新增 {len(selected_files)} 个文件/工作流、{len(selected_links)} 条高价值链接，来自 {scope_count} 个群。'
        + (f' 重点包括：{"；".join(highlights)}' if highlights else ''),
    ]
    if since:
        lines.append(f'范围：上次日报后（since {since}）')
    for scope in sorted(set([str(x.get('scope')) for x in selected_files + selected_links])):
        scope_files = group_items(selected_files).get(scope, [])[:max_per_group]
        scope_links = group_items(selected_links).get(scope, [])[:max_per_group]
        if not scope_files and not scope_links:
            continue
        lines.append(f'\n【{display_scope(scope, group_names)}】')
        if scope_files:
            lines.append('文件/工作流：')
            for item in scope_files:
                context = resource_context(str(item.get('message_text') or ''))
                description = context or file_description(str(item.get('file_name') or ''), str(item.get('kind') or 'file'))
                lines.append(f'- {describe_file(item)}：{description}')
        if scope_links:
            lines.append('重要链接：')
            for item in scope_links:
                purpose = item.get('purpose') or link_purpose(item) or '值得一看'
                lines.append(f'- {item.get("canonical_url") or item.get("url")}（用途：{purpose}；简介：{describe_link_context(item)}）')
    return redact_secrets('\n'.join(lines))


def should_run_daily_report(*, hour: int, already_sent: bool) -> bool:
    # Delivery window: 20:00 <= now < 21:00. Caller checks periodically.
    return 20 <= hour < 21 and not already_sent


def today_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime('%Y-%m-%d')

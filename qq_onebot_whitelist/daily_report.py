from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .scope_names import display_scope
from .content_utils import fallback_link_description, file_description, redact_secrets, resource_context
from .link_metadata import get_or_fetch_link_metadata
from .i18n import text as tr


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
    'pan.baidu.com',
    'www.123pan.com',
    '123pan.com',
}

STRONG_AI_TOKENS = [
    'lora', 'checkpoint', 'comfyui', 'workflow', '工作流', '提示词',
    'seedance', 'minimax', 'sora', 'kling', '可灵', 'sampler', 'denoise',
    '模型下载', '模型分享', '模型链接', 'civitai', 'huggingface',
]

MEDIA_HOSTS_WITH_AI_EXCEPTION = {
    'www.bilibili.com', 'bilibili.com',
    'www.youtube.com', 'youtube.com', 'youtu.be',
}

TRACKING_QUERY_KEYS = {
    'fbclid', 'from', 'gclid', 'igshid', 'mc_cid', 'mc_eid', 'mpshare', 'scene', 'sharer_shareinfo',
    'sharer_shareinfo_first', 'share_medium', 'share_plat', 'share_session_id', 'share_source',
    'share_tag', 'spm_id_from', 'srcid', 'trackid', 'uct2', 'vd_source',
}
MAX_ENRICHED_LINKS = 8


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
    return canonical_url(url)


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and key.lower() != 'utm' and not key.lower().startswith('utm_')
    ]
    path = parsed.path if parsed.fragment else (parsed.path.rstrip('/') or parsed.path)
    return urlunparse((parsed.scheme.lower() or 'https', host, path, '', urlencode(query), parsed.fragment))


def is_low_value_link(url: str, context: str = '') -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    text = f'{url} {context}'.lower()
    if host in LOW_VALUE_DOMAINS:
        return True
    if host in MEDIA_HOSTS_WITH_AI_EXCEPTION and not any(t in text for t in STRONG_AI_TOKENS):
        # 视频/泛分享平台：没有强 AI 信号（模型名/工作流等）一律视为低价值
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
    if host in RESOURCE_DOMAINS or any(token in text for token in STRONG_AI_TOKENS):
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
    purpose = str(item.get('purpose') or '') or link_purpose(item)
    if purpose == '核心AI资源':
        score += 3
    elif purpose == '值得一看':
        score += 1
    lowered = f'{url} {context}'.lower()
    for token in STRONG_AI_TOKENS:
        if token in lowered:
            score += 1
    return score


def describe_file(item: dict) -> str:
    name = str(item.get('file_name') or '未命名文件')
    kind = item.get('kind') or 'file'
    size = format_size(item.get('file_size'))
    return f'[{kind}] {name}（{size}）'


def describe_link_context(item: dict, store=None, *, enrich_links: bool = False, analyze_links: bool = True) -> str:
    url = str(item.get('url') or '')
    purpose = str(item.get('purpose') or (link_purpose(item) if analyze_links else '') or '值得一看')
    if enrich_links and store:
        metadata = get_or_fetch_link_metadata(store, url)
        metadata_text = ' · '.join(str(metadata.get(name) or '').strip() for name in ('title', 'description') if metadata.get(name))
        if metadata_text:
            return trim_context(metadata_text, limit=120)
    context = resource_context(str(item.get('message_text') or item.get('quoted_text') or ''), url, limit=96)
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


def build_daily_resource_report(
    store,
    *,
    limit: int = 300,
    since: str | None = None,
    max_per_group: int = 8,
    max_links: int = 20,
    include_files: bool = True,
    include_links: bool = True,
    enrich_links: bool = False,
    analyze_links: bool = True,
    max_enriched_links: int = MAX_ENRICHED_LINKS,
    language: str = 'zh-CN',
) -> str | None:
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
        score = link_score(item) if analyze_links else 0
        key = dedupe_url_key(url)
        old = deduped_links.get(key)
        if old is None or score > int(old.get('_score') or 0):
            new_item = dict(item)
            new_item['_score'] = score
            new_item['purpose'] = link_purpose(new_item) if analyze_links else ''
            new_item['canonical_url'] = canonical_url(url)
            deduped_links[key] = new_item

    selected_files = list(deduped_files.values())
    selected_links = sorted(deduped_links.values(), key=lambda x: int(x.get('_score') or 0), reverse=True)[:max(0, int(max_links))]
    if (not selected_files or not include_files) and (not selected_links or not include_links):
        return tr('daily_empty', language)

    lines = [tr('daily_title', language)]
    if selected_files and include_files:
        lines.append(tr('daily_files', language))
        for item in selected_files:
            group = display_scope(str(item.get('scope') or 'unknown'), group_names)
            lines.append(f'- {item.get("file_name") or tr("daily_unnamed", language)} · {group}')
    if selected_links and include_links:
        lines.append(tr('daily_links', language))
        for index, item in enumerate(selected_links):
            should_enrich = enrich_links and index < max(0, int(max_enriched_links))
            lines.append(f'- {item.get("canonical_url") or item.get("url")} · {describe_link_context(item, store, enrich_links=should_enrich, analyze_links=analyze_links)}')
    return redact_secrets('\n'.join(lines))


def should_run_daily_report(*, hour: int, already_sent: bool, target_hour: int = 20) -> bool:
    # Caller checks periodically; target_hour keeps the historical 20:00 default.
    return int(hour) == int(target_hour) and not already_sent


def today_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime('%Y-%m-%d')

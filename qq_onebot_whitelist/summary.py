from __future__ import annotations

import re
from typing import Any

URL_RE = re.compile(r'https?://[^\s\]）)>"\'，。；、]+', re.I)
TRAILING = '.,;:!?)]}）】》。，；：！？'


def extract_links(text: str) -> list[str]:
    seen = set()
    links = []
    for match in URL_RE.finditer(text or ''):
        url = match.group(0).rstrip(TRAILING)
        if url and url not in seen:
            seen.add(url)
            links.append(url)
    return links


def summarize_records(records: list[dict[str, Any]]) -> str:
    if not records:
        return '最近没有可总结的聊天记录。'
    texts = [str(r.get('text') or '').strip() for r in records if str(r.get('text') or '').strip()]
    links: list[str] = []
    for record in records:
        for url in record.get('links') or []:
            if url not in links:
                links.append(url)
    joined = '\n'.join(texts)
    sentences = [s.strip() for s in re.split(r'[。！？!?\n]+', joined) if s.strip()]
    lines = [f'最近 {len(records)} 条消息摘要：']
    if sentences:
        lines.append('要点：')
        for idx, item in enumerate(sentences[:8], 1):
            lines.append(f'{idx}. {item[:140]}')
    keywords = top_terms(joined)
    if keywords:
        lines.append('关键词：' + '、'.join(keywords[:10]))
    if links:
        lines.append(f'链接：{len(links)} 个')
        for url in links[:10]:
            lines.append(f'- {url}')
    return '\n'.join(lines)


def top_terms(text: str) -> list[str]:
    tokens = re.findall(r'[A-Za-z0-9_#./-]{3,}|[\u4e00-\u9fff@]{2,}', text or '')
    stop = {'https', 'http', 'www', 'com', '这个', '那个', '一下', '可以', '就是', '没有'}
    counts: dict[str, int] = {}
    for token in tokens:
        key = token.lower()
        if key in stop or key.startswith('http'):
            continue
        counts[token] = counts.get(token, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

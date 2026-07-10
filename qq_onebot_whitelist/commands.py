from __future__ import annotations

import re
from typing import Any

from .policy import extract_text, is_keepalive_event
from .summary import summarize_records
from .llm_summary import LLMConfig, summarize_records_with_fallback

HELP_TEXT = '''管理员菜单：
1. /帮助：查看本菜单
2. 资源：查看最近资源线索摘要
3. 链接：查看链接（私聊看全部，群里看本群）
4. 最近总结 [条数]：总结消息（私聊看全部最近记录，群里看本群）
5. 图片信息：查看最近处理图片（私聊看全部，群里看本群）
6. 刷新分类：重建本地图片/资源视图

说明：可省略 /，例如“帮助”“链接”“图片信息”都可以。

本地入口：
- 总入口：data/view/index.html
- 高价值资源链接：data/view/resources.html
- 高价值文件/工作流：data/view/files.html

规则：只对白名单用户或白名单群内 @ 机器人的消息回复；其他消息只记录，不回复。图片不会强制保存，只有 AI 元数据、群友好评或 AI 上下文命中才长期保留。'''.strip()


def scope_for_event(event: dict[str, Any]) -> str:
    if event.get('message_type') == 'group':
        return 'group:' + str(event.get('group_id') or 'unknown')
    return 'private:' + str(event.get('user_id') or 'unknown')


def parse_limit(text: str, default: int = 100, max_limit: int = 500) -> int:
    match = re.search(r'(\d{1,5})', text or '')
    if not match:
        return default
    value = int(match.group(1))
    if value <= 0:
        return default
    return min(value, max_limit)


def is_refresh_command(normalized: str) -> bool:
    return normalized in {'刷新', '强制刷新', '整理', '刷新分类', '重新整理', '重建分类'}


def format_view_counts(counts: dict) -> str:
    if not counts:
        return '分类视图已刷新，但当前没有可展示图片。'
    lines = ['分类视图已刷新：']
    for key, value in sorted(counts.items()):
        lines.append(f'{key}: {value}')
    return '\n'.join(lines)


def format_resources(store, *, limit: int = 20) -> str:
    files = store.recent_files(limit=limit)
    links = store.recent_link_records(limit=limit)
    if not files and not links:
        return '最近没有记录到模型文件、压缩包、工作流文件或资源链接。'
    lines = ['最近资源线索：']
    if files:
        lines.append('\n一、模型/文件')
        for idx, item in enumerate(files, 1):
            size = item.get('file_size')
            size_text = f'{size / 1024 / 1024:.1f}MB' if size else '未知大小'
            lines.append(f'{idx}. [{item.get("kind")}] {item.get("file_name")}，{size_text}，来源 {item.get("scope")} / {item.get("user_id")}')
    if links:
        lines.append('\n二、链接')
        for idx, item in enumerate(links, 1):
            context = item.get('message_text') or item.get('quoted_text') or ''
            if len(context) > 80:
                context = context[:80] + '…'
            lines.append(f'{idx}. [{item.get("kind")}] {item.get("url")}')
            if context:
                lines.append(f'   上下文：{context}')
    return '\n'.join(lines)


def build_reply(event: dict[str, Any], store, *, default_summary_limit: int = 100, max_summary_limit: int = 500, view_builder=None) -> str:
    text = extract_text(event)
    normalized = text.lower().replace(' ', '')
    scope = scope_for_event(event)
    is_private = event.get('message_type') == 'private'
    if is_keepalive_event(event):
        return '在，冒个泡。'
    if view_builder is not None and is_refresh_command(normalized):
        return format_view_counts(view_builder())
    if normalized in {'资源', '文件', '链接线索', '资源总结', '文件线索'}:
        return format_resources(store)
    if normalized in {'/帮助', '帮助', 'help', '/help'}:
        return HELP_TEXT
    if normalized.startswith('/链接') or normalized == '链接':
        if is_private:
            links = [item.get('url') for item in store.recent_link_records(limit=20)]
        else:
            links = store.recent_links(scope, limit=20)
        if not links:
            return '本会话最近没有保存到链接。'
        return '最近保存的链接：\n' + '\n'.join(f'{idx}. {url}' for idx, url in enumerate(links, 1))
    if normalized.startswith('/图片信息') or normalized == '图片信息':
        images = store.recent_images_all(limit=10) if is_private and hasattr(store, 'recent_images_all') else store.recent_images(scope, limit=10)
        if not images:
            return '本会话最近没有处理过图片。'
        lines = [f'最近处理的 {len(images)} 张图片：']
        for idx, item in enumerate(images, 1):
            size = item.get('size') or 0
            size_text = f'{size / 1024:.1f}KB' if size else '未知大小'
            ai = item.get('ai_source') or '无AI元数据'
            kept = '已保留' if item.get('kept_path') else '未保留'
            lines.append(f'{idx}. {item.get("format")} {item.get("width")}x{item.get("height")}，{size_text}，{ai}，{kept}（{item.get("retention_reason")}）')
        return '\n'.join(lines)
    if normalized.startswith('/最近总结') or normalized.startswith('最近总结'):
        limit = parse_limit(text, default=default_summary_limit, max_limit=max_summary_limit)
        records = store.recent_records_all(limit=limit) if is_private and hasattr(store, 'recent_records_all') else store.recent_records(scope, limit=limit)
        llm_config = LLMConfig.from_env()
        fallback_config = LLMConfig.ds_fallback_from_env_file()
        if llm_config or fallback_config:
            try:
                return summarize_records_with_fallback(records, llm_config, fallback_config)
            except Exception as exc:
                fallback = summarize_records(records)
                return f'大模型总结失败，已回退规则总结。\n原因：{type(exc).__name__}\n\n{fallback}'
        return summarize_records(records)
    return '已收到。发送 @机器人 /帮助 查看可用指令。'

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .policy import extract_text, is_keepalive_event
from .summary import summarize_records
from .llm_summary import LLMConfig, summarize_records_with_fallback
from .settings import read_all_day_weekdays, read_analysis_windows, write_all_day_weekdays, write_analysis_windows
from .i18n import text as tr

HELP_TEXT = '''管理员菜单：
1. 帮助：查看本菜单
2. 资源：查看最近资源线索摘要
3. 链接：查看链接（私聊看全部，群里看本群）
4. 最近总结 [条数]：总结消息（私聊看全部最近记录，群里看本群）
5. 图片信息：查看最近处理图片（私聊看全部，群里看本群）
6. 刷新分类：重建本地图片/资源视图
8. 保存图片 [分类名]：私聊回复合并聊天记录后保存图片，不填分类名默认“未分类”
9. 修复图片 [图片ID]：私聊重新下载并校验损坏图片

7. 分析时段 查看/设置/全天：私聊调整 AI 分析时间
10. 收藏夹：查看当前图片保存用法

说明：直接发送指令即可；旧的 / 前缀仍兼容。

本地入口：
- 总入口：data/view/index.html
- 高价值资源链接：data/view/resources.html
- 高价值文件/工作流：data/view/files.html

规则：只对白名单用户或白名单群内 @ 机器人的消息回复；其他消息只记录，不回复。图片不会强制保存，只有 AI 元数据、群友好评或 AI 上下文命中才长期保留。'''.strip()


def help_text(language: str = 'zh-CN') -> str:
    return '\n\n'.join((
        tr('help_title', language) + '\n' + tr('help_lines', language),
        tr('help_note', language),
        tr('help_entry', language),
        tr('help_rule', language),
    ))


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


def parse_repair_images_command(text: str) -> int | None | bool:
    """识别 /修复图片 [图片ID]；无 ID 表示扫描全部损坏图片。"""
    value = str(text or '').strip()
    match = re.fullmatch(r'(?:/\s*)?(?:修复图片|repair\s+images)(?:\s+(\d+))?', value, flags=re.IGNORECASE)
    if not match:
        return False
    return int(match.group(1)) if match.group(1) else None


def is_refresh_command(normalized: str) -> bool:
    return normalized in {'刷新', '强制刷新', '整理', '刷新分类', '重新整理', '重建分类', 'refresh', 'rebuild', 'refreshviews'}


def format_view_counts(counts: dict, language: str = 'zh-CN') -> str:
    if not counts:
        return tr('refresh_empty', language)
    lines = [tr('refresh_title', language)]
    for key, value in sorted(counts.items()):
        lines.append(f'{key}: {value}')
    return '\n'.join(lines)


def format_resources(store, *, limit: int = 20, language: str = 'zh-CN') -> str:
    files = store.recent_files(limit=limit)
    links = store.recent_link_records(limit=limit)
    if not files and not links:
        return tr('no_records', language)
    lines = [tr('resources_title', language)]
    if files:
        lines.append('\n1. ' + tr('resources_files', language))
        for idx, item in enumerate(files, 1):
            size = item.get('file_size')
            size_text = f'{size / 1024 / 1024:.1f}MB' if size else tr('unknown_size', language)
            separator = ', ' if language == 'en-US' else '，'
            lines.append(f'{idx}. [{item.get("kind")}] {item.get("file_name")}{separator}{size_text}{separator}{tr("source", language)} {item.get("scope")} / {item.get("user_id")}')
    if links:
        lines.append('\n2. ' + tr('resources_links', language))
        for idx, item in enumerate(links, 1):
            context = item.get('message_text') or item.get('quoted_text') or ''
            if len(context) > 80:
                context = context[:80] + '…'
            lines.append(f'{idx}. [{item.get("kind")}] {item.get("url")}')
            if context:
                lines.append(f'   {tr("context", language)}: {context}')
    return '\n'.join(lines)


def handle_analysis_windows_command(text: str, *, is_private: bool, config_path: str | Path, language: str = 'zh-CN') -> str | None:
    command = text.strip().lstrip('/').strip()
    if not (command.startswith('分析时段') or command.lower().startswith('analysis windows')):
        return None
    if not is_private:
        return tr('private_only', language)
    prefix = '分析时段' if command.startswith('分析时段') else 'analysis windows'
    argument = command[len(prefix):].strip()
    if argument in {'', '查看', 'view', 'View'}:
        windows = read_analysis_windows(config_path)
        value = ('、'.join(windows) if language == 'zh-CN' else ', '.join(windows)) if windows else tr('windows_all', language)
        weekdays = read_all_day_weekdays(config_path)
        if weekdays:
            label = tr('weekdays_label', language, value='、'.join(weekdays))
            value += '（' + label + '）'
        return tr('windows_current', language, value=value)
    weekend_prefix = None
    for prefix in ('周末全天', 'weekend all day', 'weekend', 'all day weekdays'):
        if argument.lower().startswith(prefix.lower()) or argument.startswith(prefix):
            weekend_prefix = prefix
            break
    if weekend_prefix:
        rest = argument[len(weekend_prefix):].strip()
        from .schedule import normalize_weekdays
        if rest in {'开', 'on', '启用', ''} and weekend_prefix in {'周末全天', 'weekend'}:
            weekdays = write_all_day_weekdays(config_path, ['sat', 'sun'])
            return tr('weekdays_set', language, value='、'.join(weekdays))
        if rest in {'关', 'off', '关闭', '取消'}:
            weekdays = write_all_day_weekdays(config_path, [])
            return tr('weekdays_off', language)
        days = write_all_day_weekdays(config_path, [d for d in rest.replace('，', ',').split(',') if d.strip()])
        return tr('weekdays_set', language, value='、'.join(days))
    if argument in {'全天', 'all', 'All day'}:
        write_analysis_windows(config_path, [])
        return tr('windows_set', language, value=tr('windows_all', language))
    set_prefix = '设置' if argument.startswith('设置') else 'set' if argument.lower().startswith('set') else None
    if set_prefix:
        values = [item.strip() for item in argument[len(set_prefix):].strip().split(',') if item.strip()]
        try:
            windows = write_analysis_windows(config_path, values)
        except ValueError as exc:
            return str(exc)
        value = ('、'.join(windows) if language == 'zh-CN' else ', '.join(windows)) if windows else tr('windows_all', language)
        return tr('windows_set', language, value=value)
    return tr('windows_usage', language)


def build_reply(event: dict[str, Any], store, *, default_summary_limit: int = 100, max_summary_limit: int = 500, view_builder=None, config_path: str | Path = 'config.yaml', language: str = 'zh-CN') -> str:
    text = extract_text(event)
    normalized = text.lower().replace(' ', '')
    scope = scope_for_event(event)
    is_private = event.get('message_type') == 'private'
    if is_keepalive_event(event):
        return tr('alive', language)
    schedule_reply = handle_analysis_windows_command(text, is_private=is_private, config_path=config_path, language=language)
    if schedule_reply is not None:
        return schedule_reply
    if view_builder is not None and is_refresh_command(normalized):
        return format_view_counts(view_builder(), language)
    if normalized in {'资源', '文件', '链接线索', '资源总结', '文件线索', 'resources', 'files', 'resourcessummary', 'resourceleads'}:
        return format_resources(store, language=language)
    if normalized in {'/帮助', '帮助', 'help', '/help'}:
        return help_text(language)
    if normalized.startswith('/链接') or normalized == '链接' or normalized.startswith('/link') or normalized == 'links':
        if is_private:
            links = [item.get('url') for item in store.recent_link_records(limit=20)]
        else:
            links = store.recent_links(scope, limit=20)
        if not links:
            return tr('no_links', language)
        return tr('links_title', language) + '\n' + '\n'.join(f'{idx}. {url}' for idx, url in enumerate(links, 1))
    if normalized.startswith('/图片信息') or normalized == '图片信息' or normalized.startswith('/imageinfo') or normalized == 'imageinfo':
        images = store.recent_images_all(limit=10) if is_private and hasattr(store, 'recent_images_all') else store.recent_images(scope, limit=10)
        if not images:
            return tr('no_images', language)
        lines = [tr('images_title', language, count=len(images))]
        for idx, item in enumerate(images, 1):
            size = item.get('size') or 0
            size_text = f'{size / 1024:.1f}KB' if size else tr('image_unknown_size', language)
            ai = item.get('ai_source') or tr('no_ai', language)
            kept = tr('kept', language) if item.get('kept_path') else tr('not_kept', language)
            separator = ', ' if language == 'en-US' else '，'
            lines.append(f'{idx}. {item.get("format")} {item.get("width")}x{item.get("height")}{separator}{size_text}{separator}{ai}{separator}{kept} ({item.get("retention_reason")})')
        return '\n'.join(lines)
    if normalized.startswith('/最近总结') or normalized.startswith('最近总结') or normalized.startswith('/recentsummary') or normalized.startswith('recentsummary'):
        limit = parse_limit(text, default=default_summary_limit, max_limit=max_summary_limit)
        records = store.recent_records_all(limit=limit) if is_private and hasattr(store, 'recent_records_all') else store.recent_records(scope, limit=limit)
        llm_config = LLMConfig.from_env()
        fallback_config = LLMConfig.ds_fallback_from_env_file()
        if llm_config or fallback_config:
            try:
                return summarize_records_with_fallback(records, llm_config, fallback_config)
            except Exception as exc:
                fallback = summarize_records(records, language=language)
                return tr('summary_failed', language, reason=type(exc).__name__, fallback=fallback)
        return summarize_records(records, language=language)
    if is_private and normalized in {'收藏夹', '收藏', 'favorites', 'fav', 'saved'}:
        # 旧 favorites 表保留用于兼容历史数据，但不再把它当作新的收藏入口；
        # 图片收藏必须由用户明确回复合并聊天记录并发送 /保存图片。
        return tr('fav_none', language)
    # 未匹配任何命令：返回空串，由调用方决定（聊天优先，否则发送通用兜底 ack）
    return ''

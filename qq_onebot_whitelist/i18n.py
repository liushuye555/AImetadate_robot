from __future__ import annotations

import ctypes
import locale
import os
from typing import Any

SUPPORTED_LANGUAGES = {'en-US', 'zh-CN'}

_TEXT = {
    'en-US': {
        'help_title': 'Administrator menu:',
        'help_lines': [
            '1. Help: show this menu',
            '2. Resources: show recent resource leads',
            '3. Links: show saved links (private chat: all; group: current group)',
            '4. Recent summary [count]: summarize recent messages',
            '5. Image info: show recently processed images',
            '6. Refresh views: rebuild local image/resource views',
            '7. Analysis windows View/Set/All day: adjust AI analysis hours in private chat',
            '8. Save images [category]: reply to a merged chat record in private chat, then save its images; default folder: Uncategorized',
            '9. Repair images [ID]: re-download and verify a damaged archived image in private chat',
            '10. Favorites: show the current image-saving instructions',
        ],
        'help_note': 'Send a command directly. The old / prefix is still supported.',
        'help_entry': 'Local pages:\n- Index: data/view/index.html\n- Resource links: data/view/resources.html\n- Files/workflows: data/view/files.html',
        'help_rule': 'Rule: replies are limited to whitelisted users/groups and @ mentions in groups. Images are retained only when they have useful metadata, feedback, or AI context value.',
        'fav_none': 'No saved chat-record images yet. In private chat, reply to a merged chat record and send /save images [category]; if omitted, the default folder is Uncategorized.',
        'fav_title': 'Your favorites ({count}):',
        'alive': 'Online.',
        'private_only': 'Analysis windows can only be changed by a whitelisted user in private chat.',
        'windows_all': 'All day',
        'windows_current': 'Current analysis windows: {value}',
        'windows_set': 'Analysis windows set: {value}',
        'windows_usage': 'Usage: Analysis windows View; Analysis windows Set 00:30-08:30,12:00-13:00; Analysis windows All day; Analysis windows Weekend all day on/off; Analysis windows Weekend all day sat,sun',
        'weekdays_label': 'All-day on: {value}',
        'weekdays_set': 'All-day analysis enabled for: {value}',
        'weekdays_off': 'All-day analysis disabled (windows only)',
        'no_records': 'No recent records found.',
        'no_links': 'No links were saved for this chat recently.',
        'links_title': 'Recently saved links:',
        'no_images': 'No images were processed for this chat recently.',
        'images_title': 'Recently processed {count} images:',
        'ack': 'Received. Send @bot Help to see available commands.',
        'summary_failed': 'LLM summary failed; rule-based summary used instead.\nReason: {reason}\n\n{fallback}',
        'daily_empty': 'No new resources today.',
        'daily_title': 'Daily resource report',
        'daily_files': 'New files:',
        'daily_links': 'New links:',
        'daily_unnamed': 'Unnamed file',
        'refresh_empty': 'Views refreshed, but there are no images to show.',
        'refresh_title': 'Views refreshed:',
        'resources_title': 'Recent resource leads:',
        'resources_files': 'Files/models',
        'resources_links': 'Links',
        'unknown_size': 'unknown size',
        'source': 'source',
        'context': 'context',
        'image_unknown_size': 'unknown size',
        'no_ai': 'no AI metadata',
        'kept': 'kept',
        'not_kept': 'not kept',
        'daily_report': 'Daily report',
        'daily_enabled': 'Enabled',
        'enrich_links': 'Enrich link titles',
        'summary_empty': 'There are no recent chat records to summarize.',
        'summary_title': 'Recent {count} message summary:',
        'summary_points': 'Key points:',
        'summary_keywords': 'Keywords:',
        'summary_links': 'Links: {count}',
    },
    'zh-CN': {
        'help_title': '管理员菜单：',
        'help_lines': [
            '1. 帮助：查看本菜单',
            '2. 资源：查看最近资源线索摘要',
            '3. 链接：查看链接（私聊看全部，群里看本群）',
            '4. 最近总结 [条数]：总结消息',
            '5. 图片信息：查看最近处理图片',
            '6. 刷新分类：重建本地图片/资源视图',
            '7. 分析时段 查看/设置/全天：私聊调整 AI 分析时间',
            '8. 保存图片 [分类名]：私聊回复合并聊天记录后保存图片，不填分类名默认“未分类”',
            '9. 修复图片 [图片ID]：私聊重新下载并校验损坏图片',
            '10. 收藏夹：查看当前图片保存用法',
        ],
        'help_note': '说明：直接发送指令即可；旧的 / 前缀仍兼容。',
        'help_entry': '本地入口：\n- 总入口：data/view/index.html\n- 高价值资源链接：data/view/resources.html\n- 高价值文件/工作流：data/view/files.html',
        'help_rule': '规则：只对白名单用户或白名单群内 @ 机器人的消息回复；其他消息只记录，不回复。图片不会强制保存，只有 AI 元数据、群友好评或 AI 上下文命中才长期保留。',
        'fav_none': '暂无聊天记录图片。请在私聊中回复一条合并聊天记录，再发送 /保存图片 [分类名]；不填分类名默认保存到“未分类”。',
        'fav_title': '你的收藏（{count} 条）：',
        'alive': '在，冒个泡。',
        'private_only': '分析时段只能由白名单用户私聊修改。',
        'windows_all': '全天',
        'windows_current': '当前允许分析时段：{value}',
        'windows_set': '已设置分析时段：{value}',
        'windows_usage': '用法：分析时段 查看；分析时段 设置 00:30-08:30,12:00-13:00；分析时段 全天；分析时段 周末全天 开/关；分析时段 周末全天 sat,sun',
        'weekdays_label': '全天开放：{value}',
        'weekdays_set': '已设置全天开放分析：{value}',
        'weekdays_off': '已取消全天开放（仅按时段）',
        'no_records': '最近没有记录到模型文件、压缩包、工作流文件或资源链接。',
        'no_links': '本会话最近没有保存到链接。',
        'links_title': '最近保存的链接：',
        'no_images': '本会话最近没有处理过图片。',
        'images_title': '最近处理的 {count} 张图片：',
        'ack': '已收到。发送 @机器人 帮助 查看可用指令。',
        'summary_failed': '大模型总结失败，已回退规则总结。\n原因：{reason}\n\n{fallback}',
        'daily_empty': '今日无新增资源。',
        'daily_title': '资源日报',
        'daily_files': '新增文件：',
        'daily_links': '新增链接：',
        'daily_unnamed': '未命名文件',
        'refresh_empty': '分类视图已刷新，但当前没有可展示图片。',
        'refresh_title': '分类视图已刷新：',
        'resources_title': '最近资源线索：',
        'resources_files': '模型/文件',
        'resources_links': '链接',
        'unknown_size': '未知大小',
        'source': '来源',
        'context': '上下文',
        'image_unknown_size': '未知大小',
        'no_ai': '无AI元数据',
        'kept': '已保留',
        'not_kept': '未保留',
        'daily_report': '日报',
        'daily_enabled': '启用',
        'enrich_links': '补充链接标题',
        'summary_empty': '最近没有可总结的聊天记录。',
        'summary_title': '最近 {count} 条消息摘要：',
        'summary_points': '要点：',
        'summary_keywords': '关键词：',
        'summary_links': '链接：{count} 个',
    },
}


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().replace('_', '-')
    if value.lower().startswith('zh'):
        return 'zh-CN'
    if value.lower().startswith('en'):
        return 'en-US'
    return value if value in SUPPORTED_LANGUAGES else None


def _windows_locale() -> str | None:
    if os.name == 'nt':
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                return buffer.value
        except Exception:
            pass
    for key in ('LANGUAGE', 'LC_ALL', 'LANG'):
        if os.environ.get(key):
            return os.environ[key]
    try:
        return locale.getlocale()[0]
    except Exception:
        return None


def effective_language(value: str | None = None) -> str:
    normalized = normalize_language(value)
    if normalized:
        return normalized
    return 'zh-CN' if (normalize_language(_windows_locale()) == 'zh-CN') else 'en-US'


def text(key: str, language: str | None = None, **kwargs: Any) -> str:
    lang = effective_language(language)
    value = _TEXT.get(lang, _TEXT['en-US']).get(key, _TEXT['en-US'].get(key, key))
    if isinstance(value, list):
        return '\n'.join(value)
    return str(value).format(**kwargs)

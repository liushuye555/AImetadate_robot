"""私聊引用合并聊天记录后的显式图片保存。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import websockets

from .images import extract_image_segments, process_image_url
from .store import Store, reply_to_message_id

DEFAULT_SAVED_CATEGORY = '未分类'
SAVED_IMAGE_REASON = 'chat_record_saved'


def clean_saved_category(value: str | None) -> str:
    """把用户输入转换成安全的单层文件夹名；空值使用默认分类。"""
    value = str(value or '').strip()
    if not value:
        return DEFAULT_SAVED_CATEGORY
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', value).strip(' .')
    return value[:80] or DEFAULT_SAVED_CATEGORY


def parse_save_images_command(text: str) -> str | None:
    """识别 ``/保存图片 [分类]``，返回清洗后的分类名；非命令返回 None。"""
    value = str(text or '').strip()
    match = re.fullmatch(r'(?:/\s*)?(?:保存图片|save\s+images)(?:\s+(.+?))?', value, flags=re.IGNORECASE)
    if not match:
        return None
    return clean_saved_category(match.group(1))


def _result(category: str, *, error: str | None = None, **counts: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        'ok': error is None,
        'category': category,
        'found': int(counts.get('found', 0)),
        'saved': int(counts.get('saved', 0)),
        'duplicates': int(counts.get('duplicates', 0)),
        'failed': int(counts.get('failed', 0)),
    }
    if error:
        result['error'] = error
    return result


MAX_FORWARD_NESTING_DEPTH = 16


def _message_segments(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a forwarded node's segment list across OneBot/NapCat shapes."""
    for key in ('message', 'content'):
        value = message.get(key)
        if isinstance(value, list):
            return [segment for segment in value if isinstance(segment, dict)]
    return []


def _forward_ids_from_message(message: dict[str, Any]) -> list[str]:
    """Extract direct nested-forward IDs, preserving their original order."""
    ids: list[str] = []
    for segment in _message_segments(message):
        if segment.get('type') != 'forward':
            continue
        value = str((segment.get('data') or {}).get('id') or '')
        if value and value not in ids:
            ids.append(value)
    if message.get('message_type') == 'forward':
        value = str((message.get('data') or {}).get('id') or '')
        if value and value not in ids:
            ids.append(value)
    return ids


async def _load_forward_nodes(action_ws, forward_ids: list[str]) -> list[tuple[str, int, int, dict[str, Any]]]:
    """Read nested merged records once each; ID tracking also breaks cycles."""
    pending = [(forward_id, 0) for forward_id in forward_ids]
    seen_ids: set[str] = set()
    nodes: list[tuple[str, int, int, dict[str, Any]]] = []
    while pending:
        forward_id, depth = pending.pop(0)
        if not forward_id or forward_id in seen_ids:
            continue
        seen_ids.add(forward_id)
        try:
            from .onebot import call_action
            response = await call_action(action_ws, 'get_forward_msg', {'id': forward_id})
        except Exception as exc:
            print(f'chat record image fetch failed: {type(exc).__name__}: {exc}')
            continue
        rows = ((response.get('data') or {}).get('messages') or []) if isinstance(response, dict) else []
        for node_index, node in enumerate(rows):
            if not isinstance(node, dict):
                continue
            nodes.append((forward_id, depth, node_index, node))
            if depth < MAX_FORWARD_NESTING_DEPTH:
                pending.extend((nested_id, depth + 1) for nested_id in _forward_ids_from_message(node))
    return nodes


async def save_replied_forward_images(store: Store, event: dict[str, Any], config) -> dict[str, Any]:
    """保存私聊命令所引用的合并聊天记录中的全部图片。"""
    category = parse_save_images_command(_event_text(event))
    if category is None:
        return _result(DEFAULT_SAVED_CATEGORY, error='command_required')
    if event.get('post_type') != 'message' or event.get('message_type') != 'private':
        return _result(category, error='private_only')
    reply_id = reply_to_message_id(event)
    if not reply_id:
        return _result(category, error='reply_required')

    from .onebot import call_action

    try:
        async with websockets.connect(config.onebot_ws_url) as action_ws:
            reply_resp = await call_action(action_ws, 'get_msg', {'message_id': reply_id})
            reply_message = (reply_resp.get('data') or {}) if isinstance(reply_resp, dict) else {}
            if not isinstance(reply_message, dict):
                return _result(category, error='forward_required')
            ids = _forward_ids_from_message(reply_message)
            if not ids:
                return _result(category, error='forward_required')

            messages = await _load_forward_nodes(action_ws, ids)
    except Exception as exc:
        print(f'chat record image connection failed: {type(exc).__name__}: {exc}')
        return _result(category, error='fetch_failed')

    images: list[tuple[str, int, int, dict[str, Any], dict[str, Any]]] = []
    for forward_id, forward_depth, node_index, node in messages:
        for image in extract_image_segments({'message': _message_segments(node)}):
            images.append((forward_id, forward_depth, node_index, node, image))
    if not images:
        return _result(category, found=0)

    user_id = str(event.get('user_id') or '')
    scope = f'private:{user_id}'
    data_dir = Path(config.data_dir)
    archive_root = data_dir / 'images' / 'ai'
    tmp_dir = data_dir / 'tmp'
    found = saved = duplicates = failed = 0
    for forward_id, forward_depth, node_index, node, image in images:
        found += 1
        try:
            result = await asyncio.to_thread(
                process_image_url,
                str(image.get('url') or ''),
                tmp_dir=tmp_dir,
                archive_root=archive_root,
                filename_hint=image.get('file'),
                nearby_text='',
                force_keep=True,
                force_reason=SAVED_IMAGE_REASON,
            )
            digest = str(result.get('sha256') or '')
            if not digest:
                raise ValueError('image hash is empty')
            if store.has_saved_image(digest, category):
                duplicates += 1
                continue
            result['retention_reason'] = SAVED_IMAGE_REASON
            result['saved_category'] = category
            store.record_image(
                scope=scope,
                user_id=user_id,
                result=result,
                raw={
                    'source': 'chat_record',
                    'reply_message_id': reply_id,
                    'forward_id': forward_id,
                    'node_index': node_index,
                    'node_user_id': str(node.get('user_id') or ''),
                    'node_nickname': str(node.get('nickname') or (node.get('sender') or {}).get('nickname') or ''),
                    'saved_category': category,
                    'image': image,
                },
            )
            saved += 1
        except Exception as exc:
            failed += 1
            print(f'chat record image save failed: {type(exc).__name__}: {exc}')
    return {
        'ok': True,
        'category': category,
        'found': found,
        'saved': saved,
        'duplicates': duplicates,
        'failed': failed,
    }


def _event_text(event: dict[str, Any]) -> str:
    parts = []
    for segment in event.get('message') or []:
        if isinstance(segment, dict) and segment.get('type') == 'text':
            parts.append(str((segment.get('data') or {}).get('text') or ''))
    return ''.join(parts).strip()


def format_save_images_result(result: dict[str, Any], language: str = 'zh-CN') -> str:
    """生成发送给用户的保存结果或用法提示。"""
    error = result.get('error')
    if error:
        if language == 'en-US':
            return {
                'command_required': 'Usage: reply to a merged chat record in private chat, then send /save images [category].',
                'private_only': 'This command only works in private chat.',
                'reply_required': 'Reply to a merged chat record first, then send /保存图片 [分类名].',
                'forward_required': 'The replied message is not a merged chat record.',
                'fetch_failed': 'Unable to read the replied chat record. Please try again later.',
            }.get(str(error), 'Unable to save images.')
        return {
            'command_required': '用法：在私聊中回复一条合并聊天记录，再发送 /保存图片 [分类名]。不填分类名默认保存到“未分类”。',
            'private_only': '“保存图片”只能在私聊中使用。',
            'reply_required': '请先回复一条合并聊天记录，再发送 /保存图片 [分类名]。',
            'forward_required': '你回复的消息不是合并聊天记录，暂时没有可保存的图片。',
            'fetch_failed': '读取聊天记录失败，请稍后重试。',
        }.get(str(error), '保存图片失败，请稍后重试。')
    category = str(result.get('category') or DEFAULT_SAVED_CATEGORY)
    if language == 'en-US':
        return (f'Saved images to {category}: found {result.get("found", 0)}, '
                f'new {result.get("saved", 0)}, duplicates {result.get("duplicates", 0)}, '
                f'failed {result.get("failed", 0)}.')
    return (f'聊天记录图片已保存到“{category}”：发现 {result.get("found", 0)} 张，'
            f'新保存 {result.get("saved", 0)} 张，重复 {result.get("duplicates", 0)} 张，'
            f'失败 {result.get("failed", 0)} 张。')


async def maybe_save_private_forward(ws, store, event: dict, config) -> bool:
    """兼容旧调用入口；现在不会因收到合并消息而自动保存。"""
    return False

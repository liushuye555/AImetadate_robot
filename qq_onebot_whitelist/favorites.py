"""私聊合并消息收藏：QQ 没有收藏夹，私聊转发给机器人的合并消息（非引用）默认保存。"""
from __future__ import annotations

import json
from typing import Any

from .store import reply_to_message_id


async def maybe_save_private_forward(ws, store, event: dict, config) -> bool:
    """私聊 + 合并消息 + 无引用 → 拉取内容并收藏；重复内容不重复存。"""
    if event.get('post_type') != 'message' or event.get('message_type') != 'private':
        return False
    if reply_to_message_id(event):
        return False  # 引用消息不默认收藏
    import websockets

    from .collection import forward_ids, is_forward_event
    from .onebot import call_action
    from .relay import build_forward_nodes, forward_content, forward_text

    if not is_forward_event(event):
        return False
    ids = forward_ids(event)
    if not ids:
        return False
    messages: list[dict] = []
    async with websockets.connect(config.onebot_ws_url) as action_ws:
        for fid in ids[:5]:
            try:
                resp = await call_action(action_ws, 'get_forward_msg', {'id': fid})
                messages.extend(((resp.get('data') or {}).get('messages') or []))
            except Exception as exc:
                print(f'favorite fetch failed: {type(exc).__name__}: {exc}')
    if not messages:
        return False
    return store.save_favorite(
        user_id=str(event.get('user_id') or ''),
        content_hash=forward_content(messages),
        forward_id=str(ids[0]),
        summary=forward_text(messages),
        nodes_json=json.dumps(build_forward_nodes(messages), ensure_ascii=False),
    )

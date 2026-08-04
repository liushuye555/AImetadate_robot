"""群搬运：把输入群的合并消息/分享型消息转发到输出群（24 小时去重，可 AI 过滤）。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .commands import scope_for_event
from .images import extract_image_segments
from .policy import extract_text
from .resources import extract_file_segments
from .summary import extract_links


def relay_input_allows(scope: str, config) -> bool:
    """输入群范围：input_groups 优先；留空按 relay 黑白名单。"""
    group_id = scope.removeprefix('group:') if scope.startswith('group:') else ''
    if not group_id:
        return False
    if config.relay_input_groups:
        return group_id in config.relay_input_groups
    if config.relay_mode == 'blacklist':
        return group_id not in config.relay_groups
    return group_id in config.relay_groups  # whitelist：空列表 = 不放行


def relay_output_groups(scope: str, config) -> list[str]:
    """输出群：output_groups 优先；留空按 relay 黑白名单（自动排除来源群）。"""
    source = scope.removeprefix('group:') if scope.startswith('group:') else ''
    if config.relay_output_groups:
        return [str(g) for g in config.relay_output_groups if str(g) and str(g) != source]
    return [str(g) for g in config.relay_groups if str(g) and str(g) != source]


def _content_key(*parts: Any) -> str:
    raw = '\n'.join(str(p) for p in parts if p)
    return hashlib.sha1(raw.encode('utf-8', errors='replace')).hexdigest()


def forward_content(messages: list[dict]) -> str:
    rows = [
        (sub.get('user_id'), sub.get('nickname'), json.dumps(sub.get('message'), ensure_ascii=False))
        for sub in messages
    ]
    return _content_key(json.dumps(rows, ensure_ascii=False))


def ordinary_content(event: dict, text: str, images: list[dict], links: list[str], files: list[str]) -> str:
    return _content_key(
        text,
        json.dumps([str(i.get('url') or '') for i in images], ensure_ascii=False),
        json.dumps(links, ensure_ascii=False),
        json.dumps(files, ensure_ascii=False),
    )


def ordinary_worth_relaying(text: str, images: list[dict], links: list[str], files: list[str], config) -> bool:
    """普通消息判定：分享型（链接/图片/文件）必转；纯文本走关键词/正则。"""
    if images or links or files:
        return True
    if config.relay_text_keywords and any(str(k) in text for k in config.relay_text_keywords):
        return True
    regex = str(config.relay_text_regex or '').strip()
    if regex:
        try:
            import re
            if re.search(regex, text):
                return True
        except Exception:
            pass
    return False


def _forward_text(messages: list[dict]) -> str:
    lines = []
    for sub in messages:
        name = str(sub.get('nickname') or (sub.get('sender') or {}).get('nickname') or '匿名')
        seg = sub.get('message') or []
        if isinstance(seg, list):
            text = ' '.join(
                str(s.get('data', {}).get('text') or '') for s in seg
                if isinstance(s, dict) and s.get('type') in ('text', 'image', 'face', 'at')
            ).strip()
        else:
            text = str(seg)
        lines.append(f'{name}: {text}')
    return '\n'.join(lines) or '[转发消息]'


def _relay_judge_ok(text: str) -> bool:
    """AI 过滤（默认关）：判断是否值得转发；LLM 不可用/出错时放行。"""
    from .collection import _llm_config, ai_match_message

    cfg = _llm_config()
    if cfg is None:
        return True
    try:
        return ai_match_message(
            (text or '')[:1500],
            '该消息是否值得转发到其他群（有实用/有趣内容，非广告、刷屏、无关闲聊）？只回答是或否。',
            cfg,
        )
    except Exception:
        return True


async def relay_event(ws, store, event: dict, config) -> None:
    """入口：搬运合并消息与分享型普通消息（后台任务，不阻塞消息循环）。"""
    if not config.relay_enabled or event.get('post_type') != 'message':
        return
    if str(event.get('user_id') or '') == str(event.get('self_id') or ''):
        return  # 不搬运机器人自己的消息
    scope = scope_for_event(event)
    if not relay_input_allows(scope, config):
        return
    targets = relay_output_groups(scope, config)
    if not targets:
        return
    from .collection import forward_ids, is_forward_event

    if is_forward_event(event):
        await relay_forward(ws, store, event, config, targets)
    else:
        await relay_ordinary(ws, store, event, config, targets)


async def relay_forward(ws, store, event: dict, config, targets: list[str]) -> None:
    from .onebot import call_action
    from .collection import forward_ids

    ids = forward_ids(event)
    if not ids:
        return
    messages: list[dict] = []
    for fid in ids[:5]:
        try:
            resp = await call_action(ws, 'get_forward_msg', {'id': fid})
            messages.extend(((resp.get('data') or {}).get('messages') or []))
        except Exception as exc:
            print(f'relay forward fetch failed: {type(exc).__name__}: {exc}')
    if not messages:
        return
    key = forward_content(messages)
    if store.relay_seen(key, hours=config.relay_dedupe_hours):
        return
    if config.relay_ai_filter and not _relay_judge_ok(_forward_text(messages)):
        return
    nodes = []
    for sub in messages:
        seg = sub.get('message') or []
        nodes.append({
            'type': 'node',
            'data': {
                'name': str(sub.get('nickname') or (sub.get('sender') or {}).get('nickname') or '匿名'),
                'uin': str(sub.get('user_id') or ''),
                'content': seg if isinstance(seg, list) else str(seg),
            },
        })
    for gid in targets:
        try:
            await call_action(ws, 'send_forward_msg', {'group_id': int(gid), 'messages': nodes})
        except Exception as exc:
            print(f'relay send_forward failed to {gid}: {type(exc).__name__}: {exc}; fallback text')
            await call_action(ws, 'send_group_msg', {'group_id': int(gid), 'message': _forward_text(messages)})
    store.relay_log(key, 'forward')


async def relay_ordinary(ws, store, event: dict, config, targets: list[str]) -> None:
    from .onebot import call_action

    text = extract_text(event)
    images = extract_image_segments(event)
    links = extract_links(text)
    files = [str(f.get('file_name') or '') for f in extract_file_segments(event)]
    if not ordinary_worth_relaying(text, images, links, files, config):
        return
    key = ordinary_content(event, text, images, links, files)
    if store.relay_seen(key, hours=config.relay_dedupe_hours):
        return
    if config.relay_ai_filter and not _relay_judge_ok(text):
        return
    message = event.get('message') or (text or '[图片]')
    for gid in targets:
        try:
            await call_action(ws, 'send_group_msg', {'group_id': int(gid), 'message': message})
        except Exception as exc:
            print(f'relay ordinary failed to {gid}: {type(exc).__name__}: {exc}')
    store.relay_log(key, 'ordinary')

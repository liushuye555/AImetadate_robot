"""带人设与简单记忆的聊天回复：管理员长记忆，其他人短记忆（以其最近一次交流为准）。"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import netutil
from .commands import scope_for_event
from .llm_summary import LLMConfig
from .policy import extract_text

_REPO_ROOT = Path(__file__).resolve().parents[1]
_cooldown: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def _user_key(scope: str, user_id: str) -> str:
    return f'{scope}:{user_id}'


def _cooldown_ok(config, scope: str, user_id: str) -> bool:
    key = _user_key(scope, user_id)
    now = time.monotonic()
    with _cooldown_lock:
        last = _cooldown.get(key, 0.0)
        if now - last < max(1, int(config.chat_cooldown_seconds)):
            return False
        _cooldown[key] = now
    if len(_cooldown) > 1000:
        with _cooldown_lock:
            _cooldown.clear()
    return True


def _memory_turns(store, scope: str, user_id: str, config) -> str:
    """最近对话记忆：管理员更长，普通人较短。"""
    limit = (
        int(config.chat_admin_memory_turns)
        if str(user_id) in config.bot.whitelist_users
        else int(config.chat_memory_turns)
    )
    turns = store.recent_chat_turns(scope, user_id, limit)
    lines = []
    for turn in turns:
        role = 'assistant' if str(turn.get('role')) == 'bot' else 'user'
        lines.append(f'{role}: {turn.get("text") or ""}')
    return '\n'.join(lines)


def _llm_chat(persona: str, memory: str, text: str, config) -> str:
    """调用 DeepSeek 生成回复；失败返回空串（不打扰）。"""
    cfg = LLMConfig.ds_fallback_from_env_file(_REPO_ROOT / '.env')
    if cfg is None or not cfg.api_key:
        return ''
    system = (
        (str(persona or '').strip() or '你是一个友好的 QQ 机器人助手。')
        + '\n以下是你们之前的简短对话记忆：\n'
        + (memory or '（无）')
        + '\n请基于人设自然回复，保持简短（不超过 120 字），不要说破你在使用模型。'
    )
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': (text or '')[:800]},
        ],
        'temperature': 0.7,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {cfg.api_key}'},
        method='POST',
    )
    try:
        with netutil.open_url(req, timeout=cfg.timeout_seconds or 30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return str((data.get('choices') or [{}])[0].get('message', {}).get('content') or '').strip()
    except Exception:
        return ''


def maybe_chat_reply(store, event: dict, config) -> str | None:
    """返回聊天回复文本（无则不回）。仅由已通过回复门槛的消息触发。"""
    if not config.chat_enabled or event.get('post_type') != 'message':
        return None
    scope = scope_for_event(event)
    user_id = str(event.get('user_id') or '')
    text = extract_text(event)
    if not user_id or not text.strip():
        return None
    if event.get('message_type') == 'group':
        group_id = str(event.get('group_id') or '')
        if config.chat_groups and group_id not in config.chat_groups:
            return None  # 限定了聊天群，且当前群不在列表内
    if not _cooldown_ok(config, scope, user_id):
        return None
    memory = _memory_turns(store, scope, user_id, config)
    reply = _llm_chat(config.chat_persona, memory, text, config)
    if reply:
        store.record_chat_turn(scope, user_id, 'user', text)
        store.record_chat_turn(scope, user_id, 'bot', reply)
    return reply or None

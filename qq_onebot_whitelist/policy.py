from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BotConfig:
    whitelist_users: set[str] = field(default_factory=set)
    whitelist_groups: set[str] = field(default_factory=set)
    require_at_in_group: bool = True
    allow_group_admins: bool = True


def extract_text(event: dict[str, Any]) -> str:
    message = event.get('message')
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts = []
        for seg in message:
            if seg.get('type') == 'text':
                parts.append(str((seg.get('data') or {}).get('text') or ''))
        return ''.join(parts).strip()
    return str(event.get('raw_message') or '').strip()


def is_at_all(event: dict[str, Any]) -> bool:
    message = event.get('message')
    if isinstance(message, list):
        for seg in message:
            if seg.get('type') == 'at' and str((seg.get('data') or {}).get('qq') or '').lower() == 'all':
                return True
    return '[CQ:at,qq=all]' in str(event.get('raw_message') or '').lower()


def is_directly_mentioned(event: dict[str, Any], self_id: str | int | None = None) -> bool:
    self_text = str(self_id if self_id is not None else event.get('self_id') or '')
    message = event.get('message')
    if isinstance(message, list):
        for seg in message:
            if seg.get('type') != 'at':
                continue
            qq = str((seg.get('data') or {}).get('qq') or '')
            if qq == self_text:
                return True
    raw = str(event.get('raw_message') or '')
    return bool(self_text and f'[CQ:at,qq={self_text}]' in raw)


def is_group_admin(event: dict[str, Any]) -> bool:
    role = str((event.get('sender') or {}).get('role') or '').lower()
    return role in {'admin', 'owner'}


def is_keepalive_event(event: dict[str, Any]) -> bool:
    text = extract_text(event)
    if not is_at_all(event):
        return False
    keywords = ['清群', '清人', '清死人', '死人', '冒泡', '保活', '在线的', '不说话', '踢人']
    return any(k in text for k in keywords)


def sender_allowed(event: dict[str, Any], config: BotConfig) -> bool:
    user_id = str(event.get('user_id') or '')
    group_id = str(event.get('group_id') or '')
    if user_id in config.whitelist_users or group_id in config.whitelist_groups:
        return True
    if config.allow_group_admins and event.get('message_type') == 'group' and is_group_admin(event):
        return True
    return False


def should_reply(event: dict[str, Any], config: BotConfig) -> bool:
    if event.get('post_type') != 'message':
        return False
    if event.get('message_type') == 'private':
        return sender_allowed(event, config)
    if not sender_allowed(event, config):
        return False
    if event.get('message_type') == 'group' and config.require_at_in_group:
        if is_keepalive_event(event) and is_group_admin(event):
            return True
        return is_directly_mentioned(event, event.get('self_id'))
    return True


# Backward-compatible alias for old imports/tests.
def is_mentioned(event: dict[str, Any], self_id: str | int | None = None) -> bool:
    return is_directly_mentioned(event, self_id)

"""群级采集策略：按群配置采集类型（图片/链接/文件/转发），未配置的群默认全部采集。"""
from __future__ import annotations

import json
from typing import Any

from .config import AppConfig


COLLECTION_KINDS = ("images", "links", "files", "forwards")


def collection_allows(scope: str, kind: str, config: AppConfig) -> bool:
    """未配置的群采集全部类型；已配置的群按 profile 勾选结果判定。"""
    profile = config.collection_groups.get(scope)
    if profile is None:
        return True
    return bool(profile.get(kind, True))


def is_forward_event(event: dict[str, Any]) -> bool:
    """判断消息是否为转发消息（OneBot 转发段或转发类型）。"""
    return event.get("message_type") == "forward" or "forward" in json.dumps(event, ensure_ascii=False)

import asyncio
import json

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import _send_group_message, keepalive_targets
from qq_onebot_whitelist.policy import BotConfig


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_keepalive_targets_custom_mode_uses_configured_groups(tmp_path):
    config = AppConfig(
        data_dir=tmp_path,
        bot=BotConfig(),
        keepalive_enabled=True,
        keepalive_interval_minutes=30,
        keepalive_mode="custom",
        keepalive_groups={"123"},
        keepalive_message="在线检查",
    )
    targets = asyncio.run(keepalive_targets(None, config))
    assert targets == {"123"}


def test_send_group_message_payload(tmp_path):
    ws = FakeWS()
    config = AppConfig(data_dir=tmp_path, bot=BotConfig())
    asyncio.run(_send_group_message(ws, "123", "在线检查"))
    assert ws.sent == [{"action": "send_group_msg", "params": {"group_id": 123, "message": "在线检查"}}]

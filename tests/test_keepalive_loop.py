import asyncio
import json

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import send_keepalive
from qq_onebot_whitelist.policy import BotConfig


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_send_keepalive_targets_only_configured_groups(tmp_path):
    ws = FakeWS()
    config = AppConfig(data_dir=tmp_path, bot=BotConfig(), keepalive_enabled=True, keepalive_interval_minutes=30, keepalive_groups={'123'}, keepalive_message='在线检查')

    asyncio.run(send_keepalive(ws, config))

    assert ws.sent == [{'action': 'send_group_msg', 'params': {'group_id': 123, 'message': '在线检查'}}]

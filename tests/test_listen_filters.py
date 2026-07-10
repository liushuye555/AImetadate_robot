import asyncio

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import handle_event
from qq_onebot_whitelist.policy import BotConfig
from qq_onebot_whitelist.store import Store


class FakeWS:
    def __init__(self):
        self.sent = []
    async def send(self, payload):
        self.sent.append(payload)


def test_blocked_group_is_ignored_without_record_or_reply(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = AppConfig(data_dir=tmp_path, bot=BotConfig(whitelist_users={'200000001'}), blocked_groups={'100000001'})
        event = {
            'post_type': 'message',
            'message_type': 'group',
            'group_id': 100000001,
            'user_id': 200000001,
            'self_id': 200000002,
            'message': [
                {'type': 'at', 'data': {'qq': '200000002'}},
                {'type': 'text', 'data': {'text': ' /帮助'}},
            ],
        }
        ws = FakeWS()

        replied = await handle_event(ws, event, cfg, store)

        assert replied is False
        assert ws.sent == []
        assert store.recent_records('group:100000001') == []

    asyncio.run(scenario())

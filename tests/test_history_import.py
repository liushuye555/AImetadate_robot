import asyncio
import json

from qq_onebot_whitelist.history_import import import_group_history_once
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.policy import BotConfig
from qq_onebot_whitelist.store import Store


class FakeWS:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
    async def send(self, payload):
        self.sent.append(json.loads(payload))
    async def recv(self):
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def test_import_group_history_once_records_messages(tmp_path):
    async def scenario():
        response = {
            'status': 'ok',
            'retcode': 0,
            'echo': 'history',
            'data': {
                'messages': [
                    {
                        'post_type': 'message',
                        'message_type': 'group',
        'group_id': 100000002,
                        'user_id': 1001,
        'self_id': 200000002,
                        'message_seq': 123,
                        'message': [{'type': 'text', 'data': {'text': 'comfyui 放大节点怎么用'}}],
                    }
                ]
            },
        }
        ws = FakeWS([response])
        store = Store(tmp_path / 'bot.db')
        cfg = AppConfig(data_dir=tmp_path, bot=BotConfig())

        imported, next_seq = await import_group_history_once(ws, cfg, store, group_id=100000002, count=10)

        assert imported == 1
        assert next_seq == 123
        assert store.recent_records('group:100000002')[0]['text'] == 'comfyui 放大节点怎么用'
        assert ws.sent[0]['action'] == 'get_group_msg_history'
        assert ws.sent[0]['params']['reverse_order'] is False

    asyncio.run(scenario())


def test_import_group_history_once_dedupes_seen_boundary(tmp_path):
    async def scenario():
        response = {
            'status': 'ok',
            'retcode': 0,
            'echo': 'history',
            'data': {
                'messages': [
                    {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'user_id': 1, 'message_seq': 100, 'message': 'old'},
                    {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'user_id': 1, 'message_seq': 101, 'message': 'seen'},
                ]
            },
        }
        ws = FakeWS([response])
        store = Store(tmp_path / 'bot.db')
        cfg = AppConfig(data_dir=tmp_path, bot=BotConfig())
        seen = {101}

        imported, next_seq = await import_group_history_once(ws, cfg, store, group_id=1, count=10, message_seq=101, reverse_order=True, seen=seen)

        assert imported == 1
        assert next_seq == 100
        assert [r['text'] for r in store.recent_records('group:1')] == ['old']
        assert ws.sent[0]['params']['reverse_order'] is True

    asyncio.run(scenario())

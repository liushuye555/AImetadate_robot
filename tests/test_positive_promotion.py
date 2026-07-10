import asyncio
from pathlib import Path

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import handle_event
from qq_onebot_whitelist.policy import BotConfig
from qq_onebot_whitelist.store import Store


class FakeWS:
    def __init__(self):
        self.sent = []
    async def send(self, payload):
        self.sent.append(payload)


def test_positive_feedback_promotes_recent_candidate(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = AppConfig(data_dir=tmp_path, bot=BotConfig(), candidate_ttl_hours=24)
        candidate = tmp_path / 'images' / 'candidates' / 'aa' / 'abc.png'
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b'image')
        store.record_image(
            scope='group:1',
            user_id='1001',
            result={
                'url': 'u', 'sha256': 'abc', 'size': 1000000, 'format': 'PNG', 'width': 1024, 'height': 1536,
                'metadata_keys': [], 'has_ai_metadata': False, 'ai_source': None, 'text_excerpt': '',
                'kept_path': str(candidate), 'retention_reason': 'candidate',
            },
            raw={},
        )
        event = {
            'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'user_id': 1002,
            'message': [{'type': 'text', 'data': {'text': '这张太神了，求提示词'}}],
        }

        await handle_event(FakeWS(), event, cfg, store)

        images = store.recent_images('group:1', limit=5)
        assert any(img['retention_reason'] == 'positive_feedback' and img['kept_path'] for img in images)
        assert not candidate.exists()

    asyncio.run(scenario())

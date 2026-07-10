from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import record_event
from qq_onebot_whitelist.store import Store


def test_record_event_stores_each_link_once(tmp_path):
    store = Store(tmp_path / 'bot.db')
    config = AppConfig(data_dir=tmp_path)
    event = {
        'post_type': 'message',
        'message_type': 'group',
        'group_id': 1,
        'user_id': 2,
        'message_id': 3,
        'raw_message': '模型 https://civitai.com/models/123',
        'message': [{'type': 'text', 'data': {'text': '模型 https://civitai.com/models/123'}}],
    }

    record_event(store, event, config)

    links = store.recent_link_records(limit=10)
    assert len(links) == 1
    assert links[0]['url'] == 'https://civitai.com/models/123'

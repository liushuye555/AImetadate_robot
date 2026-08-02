import asyncio

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import startup_history_catchup
from qq_onebot_whitelist.store import Store


def test_startup_history_stops_paging_at_saved_newest(monkeypatch, tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.update_history_cursor('1', newest_seq='100')
    config = AppConfig(
        data_dir=tmp_path,
        startup_history_enabled=True,
        startup_history_mode='whitelist',
        startup_history_groups={'1'},
        startup_history_pages=5,
        startup_history_count=50,
        startup_history_all=False,
    )
    calls = []

    async def fake_call(ws, action, params):
        calls.append((action, params))
        return {'data': {'messages': [
            {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'message_seq': 102, 'message': 'new'},
            {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'message_seq': 100, 'message': 'known'},
            {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'message_seq': 99, 'message': 'old'},
        ]}}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)
    monkeypatch.setattr('qq_onebot_whitelist.onebot.record_event', lambda *args: None)

    asyncio.run(startup_history_catchup(object(), config, store))

    assert len(calls) == 1
    assert store.get_history_cursor('1')['newest_seq'] == '102'

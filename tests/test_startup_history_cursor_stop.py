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


def test_startup_history_stops_when_pages_yield_no_new_rows(monkeypatch, tmp_path):
    """游标消息已被清理时：连续多页零新入库即提前止损，不再翻满 max_pages。"""
    from qq_onebot_whitelist import onebot

    store = Store(tmp_path / 'bot.db')
    store.update_history_cursor('1', newest_seq='99999')  # 永远翻不到
    config = AppConfig(
        data_dir=tmp_path,
        startup_history_enabled=True,
        startup_history_mode='whitelist',
        startup_history_groups={'1'},
        startup_history_pages=5,
        startup_history_max_pages=200,
        startup_history_count=50,
        startup_history_all=False,
    )
    calls = []

    async def fake_call(ws, action, params):
        calls.append(params)
        start = params['message_seq'] or 1000
        first = start - 1 if params.get('reverse_order') else start
        return {'data': {'messages': [
            {'post_type': 'message', 'message_type': 'group', 'group_id': 1,
             'message_seq': first, 'message': f'm{first}'},
            {'post_type': 'message', 'message_type': 'group', 'group_id': 1,
             'message_seq': first - 1, 'message': f'm{first - 1}'},
        ]}}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)
    # 全部"已入库"：record_event 恒 False → 每页零新入库
    monkeypatch.setattr('qq_onebot_whitelist.onebot.record_event', lambda *args: False)

    asyncio.run(startup_history_catchup(object(), config, store))

    assert len(calls) == onebot.STARTUP_HISTORY_STALL_PAGES

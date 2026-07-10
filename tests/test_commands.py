from qq_onebot_whitelist.commands import build_reply, scope_for_event
from qq_onebot_whitelist.store import Store


def test_build_reply_recent_links_and_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'bot.db')
    event = {'message_type': 'group', 'group_id': 1, 'user_id': 1001, 'message': '/链接'}
    scope = scope_for_event(event)
    store.record_message(scope=scope, user_id='1001', text='资料 https://a.test', raw={})

    link_reply = build_reply(event, store)
    summary_reply = build_reply({**event, 'message': '/最近总结 50'}, store)

    assert 'https://a.test' in link_reply
    assert '最近 1 条消息摘要' in summary_reply

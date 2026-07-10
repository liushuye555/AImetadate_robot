from qq_onebot_whitelist.store import Store


def test_last_ai_context_end_message_id(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert store.last_ai_context_end_message_id('group:1') == 0
    store.record_ai_context_batch(scope='group:1', start_message_id=1, end_message_id=10, model='m', summary='a')
    store.record_ai_context_batch(scope='group:1', start_message_id=11, end_message_id=20, model='m', summary='b')
    store.record_ai_context_batch(scope='group:2', start_message_id=1, end_message_id=99, model='m', summary='c')
    assert store.last_ai_context_end_message_id('group:1') == 20

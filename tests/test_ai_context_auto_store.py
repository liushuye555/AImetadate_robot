from qq_onebot_whitelist.store import Store


def test_count_new_messages_after_analyzed(tmp_path):
    store = Store(tmp_path / 'bot.db')
    for i in range(5):
        store.record_message(scope='group:1', user_id='u', text=f'msg{i}', raw={})
    store.record_ai_context_batch(scope='group:1', start_message_id=1, end_message_id=3, model='m', summary='s')
    assert store.count_messages_after('group:1', 3) == 2
    assert store.max_message_id('group:1') == 5

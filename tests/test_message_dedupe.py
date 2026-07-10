from qq_onebot_whitelist.store import Store


def test_record_message_dedupes_by_scope_and_message_key(tmp_path):
    store = Store(tmp_path / 'bot.db')
    raw = {'message_id': 123, 'message_seq': 123}
    assert store.record_message(scope='group:1', user_id='u', text='hello', raw=raw) == []
    assert store.record_message(scope='group:1', user_id='u', text='hello again', raw=raw) == []
    assert store.count_messages_after('group:1', 0) == 1

    # Same message id in another scope is independent.
    store.record_message(scope='group:2', user_id='u', text='hello', raw=raw)
    assert store.count_messages_after('group:2', 0) == 1

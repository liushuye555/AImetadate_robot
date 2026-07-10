from qq_onebot_whitelist.store import Store


def test_history_cursor_roundtrip(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert store.get_history_cursor('123') is None
    store.update_history_cursor('123', newest_seq='n10', oldest_seq='o1')
    cursor = store.get_history_cursor('123')
    assert cursor['group_id'] == '123'
    assert cursor['newest_seq'] == 'n10'
    assert cursor['oldest_seq'] == 'o1'

    store.update_history_cursor('123', newest_seq='n12')
    cursor = store.get_history_cursor('123')
    assert cursor['newest_seq'] == 'n12'
    assert cursor['oldest_seq'] == 'o1'

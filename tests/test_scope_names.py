from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist.scope_names import display_scope


def test_display_scope_uses_latest_group_name(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_message(scope='group:123', user_id='u', text='x', raw={'message_id': 1, 'group_id': 123, 'group_name': '测试群'})

    assert display_scope('group:123', store.group_name_map()) == '测试群（123）'
    assert display_scope('group:999', store.group_name_map()) == 'group:999'

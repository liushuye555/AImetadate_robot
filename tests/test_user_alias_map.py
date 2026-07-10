from qq_onebot_whitelist.ai_context_analyze import user_alias_map


def test_user_alias_map_is_stable_order():
    assert user_alias_map([
        {'user_id': '200000001', 'nickname': 'TestUser', 'card': 'TestCard'},
        {'user_id': '999', 'nickname': 'OtherUser', 'card': 'OtherCard'},
        {'user_id': '200000001', 'nickname': 'TestUser', 'card': 'TestCard'},
    ]) == {
        'U1': {'user_id': '200000001', 'nickname': 'TestUser', 'card': 'TestCard'},
        'U2': {'user_id': '999', 'nickname': 'OtherUser', 'card': 'OtherCard'},
    }

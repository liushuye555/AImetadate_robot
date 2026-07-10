from qq_onebot_whitelist.policy import BotConfig, is_at_all, is_directly_mentioned, is_keepalive_event, should_reply


def group_event(text, *, role='member', user_id='1001', self_id='3001'):
    return {
        'post_type': 'message',
        'message_type': 'group',
        'group_id': 2001,
        'user_id': user_id,
        'self_id': self_id,
        'sender': {'role': role},
        'message': [
            {'type': 'at', 'data': {'qq': 'all'}},
            {'type': 'text', 'data': {'text': text}},
        ],
        'raw_message': '[CQ:at,qq=all] ' + text,
    }


def test_at_all_is_not_direct_mention():
    event = group_event('普通通知')
    assert is_at_all(event) is True
    assert is_directly_mentioned(event, 3001) is False


def test_at_all_does_not_trigger_normal_reply_for_whitelist_user():
    event = group_event('普通通知', user_id='200000001')
    config = BotConfig(whitelist_users={'200000001'}, require_at_in_group=True)
    assert should_reply(event, config) is False


def test_admin_at_all_keepalive_triggers_reply():
    event = group_event('清群，死人冒泡', role='admin')
    config = BotConfig(whitelist_users=set(), require_at_in_group=True, allow_group_admins=True)
    assert is_keepalive_event(event) is True
    assert should_reply(event, config) is True


def test_member_at_all_keepalive_does_not_trigger_without_whitelist_or_admin():
    event = group_event('清群，死人冒泡', role='member')
    config = BotConfig(whitelist_users=set(), require_at_in_group=True, allow_group_admins=True)
    assert should_reply(event, config) is False

from qq_onebot_whitelist.policy import BotConfig, should_reply, extract_text, is_mentioned


def group_event(user_id='1001', group_id='2001', self_id='3001', text='hello'):
    return {
        'post_type': 'message',
        'message_type': 'group',
        'user_id': int(user_id),
        'group_id': int(group_id),
        'self_id': int(self_id),
        'message': [
            {'type': 'text', 'data': {'text': text}},
        ],
    }


def at_group_event(user_id='1001', group_id='2001', self_id='3001', text='/帮助'):
    return {
        'post_type': 'message',
        'message_type': 'group',
        'user_id': int(user_id),
        'group_id': int(group_id),
        'self_id': int(self_id),
        'message': [
            {'type': 'at', 'data': {'qq': self_id}},
            {'type': 'text', 'data': {'text': ' ' + text}},
        ],
    }


def test_extract_text_from_onebot_segments_skips_at():
    assert extract_text(at_group_event(text='/总结 100')) == '/总结 100'


def test_is_mentioned_detects_at_self():
    assert is_mentioned(at_group_event(self_id='3001'), self_id='3001') is True
    assert is_mentioned(group_event(self_id='3001'), self_id='3001') is False


def test_non_whitelist_never_replies_even_when_at():
    cfg = BotConfig(whitelist_users={'9999'})
    assert should_reply(at_group_event(user_id='1001'), cfg) is False


def test_whitelist_without_at_does_not_reply_in_group():
    cfg = BotConfig(whitelist_users={'1001'})
    assert should_reply(group_event(user_id='1001'), cfg) is False


def test_whitelist_with_at_replies_in_group():
    cfg = BotConfig(whitelist_users={'1001'})
    assert should_reply(at_group_event(user_id='1001'), cfg) is True


def test_private_whitelist_can_reply_without_at():
    cfg = BotConfig(whitelist_users={'1001'})
    event = {'post_type': 'message', 'message_type': 'private', 'user_id': 1001, 'message': '帮助'}
    assert should_reply(event, cfg) is True

from qq_onebot_whitelist.llm_summary import _format_records


def test_format_records_includes_compact_user_table_with_card_and_nickname():
    text = _format_records([
        {
            'id': 123,
            'seen_at': '2026-07-07 03:21:00',
            'user_id': '200000001',
            'nickname': 'TestUser',
            'card': 'TestCard',
            'text': 'prompt: 1girl, cyberpunk city',
            'links': [],
        },
        {
            'id': 124,
            'seen_at': '2026-07-07 03:22:00',
            'user_id': '999',
            'nickname': 'OtherUser',
            'card': 'OtherCard',
            'text': 'TestUser 这个怎么出的？',
            'links': [],
        },
    ])
    assert '用户表：U1=TestCard/TestUser；U2=OtherCard/OtherUser' in text
    assert '#123 U1 03:21 prompt: 1girl, cyberpunk city' in text
    assert '#124 U2 03:22 TestUser 这个怎么出的？' in text

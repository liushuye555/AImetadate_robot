from qq_onebot_whitelist.llm_summary import _format_records


def test_format_records_uses_compact_ids_user_aliases_and_time():
    text = _format_records([
        {'id': 123, 'seen_at': '2026-07-07 03:21:00', 'user_id': '200000001', 'text': 'prompt: 1girl, cyberpunk city', 'links': []},
        {'id': 124, 'seen_at': '2026-07-07 03:22:00', 'user_id': '999', 'text': '求提示词', 'links': []},
        {'id': 125, 'seen_at': '2026-07-07 03:23:00', 'user_id': '200000001', 'text': '补充：CFG 3.5', 'links': []},
    ])
    assert '#123 U1 03:21 prompt: 1girl, cyberpunk city' in text
    assert '#124 U2 03:22 求提示词' in text
    assert '#125 U1 03:23 补充：CFG 3.5' in text

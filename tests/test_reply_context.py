from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist.summary import summarize_records
from qq_onebot_whitelist.llm_summary import _format_records


def test_recent_records_include_quoted_text_from_reply(tmp_path):
    store = Store(tmp_path / 'bot.db')
    scope = 'group:1'
    target = {
        'message_id': 123,
        'message_seq': 123,
        'message': [{'type': 'text', 'data': {'text': '原提示词：1girl, white hair'}}],
    }
    reply = {
        'message_id': 124,
        'message_seq': 124,
        'message': [
            {'type': 'reply', 'data': {'id': '123'}},
            {'type': 'text', 'data': {'text': '这个怎么出的'}}
        ],
    }
    store.record_message(scope=scope, user_id='u1', text='原提示词：1girl, white hair', raw=target)
    store.record_message(scope=scope, user_id='u2', text='这个怎么出的', raw=reply)

    records = store.recent_records(scope, limit=5)

    assert records[-1]['quoted_text'] == '原提示词：1girl, white hair'
    assert records[-1]['reply_to_message_id'] == '123'
    assert '引用：原提示词' in _format_records(records)

from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist.summary import extract_links, summarize_records


def test_extract_links_dedupes_and_strips_punctuation():
    text = '资料 https://example.com/a?b=1，备用 https://example.com/a?b=1 还有 http://x.test/y).'
    assert extract_links(text) == ['https://example.com/a?b=1', 'http://x.test/y']


def test_store_records_messages_links_and_summarizes(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_message(scope='group:1', user_id='1001', text='第一条 https://a.test', raw={'id': 1})
    store.record_message(scope='group:1', user_id='1001', text='第二条：讨论白名单@回复', raw={'id': 2})

    records = store.recent_records('group:1', limit=10)
    links = store.recent_links('group:1', limit=10)
    summary = summarize_records(records)

    assert links == ['https://a.test']
    assert '最近 2 条消息摘要' in summary
    assert '白名单@回复' in summary

from qq_onebot_whitelist.daily_report import canonical_url, is_low_value_link, link_score, trim_context
from qq_onebot_whitelist.store import Store


def test_resource_link_report_filters_dedupes_and_keeps_better_context(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/example-test', message_text='测试短视频分享')
    store.record_link(scope='group:1', user_id='u1', url='https://civitai.com/models/123/model?utm=abc', message_text='好用的 lora')
    store.record_link(scope='group:1', user_id='u2', url='https://civitai.com/models/123/model', message_text='重复')

    selected = {}
    for item in store.recent_link_records(limit=100):
        context = item.get('message_text') or item.get('quoted_text') or ''
        if is_low_value_link(item['url'], context):
            continue
        score = link_score(item)
        if score <= 0:
            continue
        key = canonical_url(item['url'])
        if key not in selected or score > selected[key]['score']:
            selected[key] = {'scope': item['scope'], 'url': key, 'context': trim_context(context), 'score': score}

    assert list(selected.values()) == [{'scope': 'group:1', 'url': 'https://civitai.com/models/123/model', 'context': '好用的 lora', 'score': 5}]

from qq_onebot_whitelist.daily_report import build_daily_resource_report
from qq_onebot_whitelist.store import Store


def test_daily_report_uses_since_time_dedupes_and_filters_low_value_links(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/example-test', message_text='测试短视频分享')
    store.record_link(scope='group:1', user_id='u1', url='https://civitai.com/models/123/model', message_text='这个 lora 效果不错')
    store.record_link(scope='group:1', user_id='u2', url='https://civitai.com/models/123/model?utm=abc', message_text='重复发一下')
    store.record_link(scope='group:1', user_id='u2', url='https://weird-tools.example/paint', message_text='神奇小网站，可以在线试试效果')
    store.record_file(scope='group:1', user_id='u3', file_name='example-workflow.json', file_size=12345, url='https://very.long/download/url', kind='workflow', raw={})

    report = build_daily_resource_report(store, since='1970-01-01 00:00:00')

    assert report is not None
    assert 'group:1' in report
    assert '快手' not in report
    assert 'v.kuaishou.com' not in report
    assert report.count('civitai.com/models/123/model') == 1
    assert 'weird-tools.example/paint' in report
    assert '神奇小网站' in report
    assert 'example-workflow.json' in report
    assert 'https://very.long/download/url' not in report
    assert '新增文件：' in report
    assert '新增链接：' in report


def test_daily_report_redacts_keys_from_link_context(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://github.com/a/b', message_text='测试 key sk-abcdefghijklmnopqrstuvwxyz')

    report = build_daily_resource_report(store, since='1970-01-01 00:00:00')

    assert 'sk-abcdefghijklmnopqrstuvwxyz' not in report
    assert '[已脱敏密钥]' in report


def test_daily_report_reports_empty_when_only_low_value_items_exist(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/example-test', message_text='测试短视频分享')

    assert build_daily_resource_report(store, since='1970-01-01 00:00:00') == '今日无新增资源。'


def test_daily_report_prioritizes_scored_links_and_applies_limit(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://unknown.example/item', message_text='普通分享')
    store.record_link(scope='group:1', user_id='u', url='https://github.com/a/b', message_text='项目源码')
    store.record_link(scope='group:1', user_id='u', url='https://other.example/item', message_text='另一个分享')

    report = build_daily_resource_report(store, max_links=1)

    assert 'https://github.com/a/b' in report
    assert 'https://unknown.example/item' not in report
    assert 'https://other.example/item' not in report


def test_daily_report_uses_cached_page_metadata_when_enabled(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://example.com/page', message_text='')
    monkeypatch.setattr(
        'qq_onebot_whitelist.daily_report.get_or_fetch_link_metadata',
        lambda store, url: {'title': '页面标题', 'description': '页面简介'},
    )

    report = build_daily_resource_report(store, enrich_links=True, max_links=1)

    assert '页面标题' in report
    assert '页面简介' in report


def test_daily_report_respects_configured_metadata_limit(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://example.com/one', message_text='one')
    store.record_link(scope='group:1', user_id='u', url='https://example.com/two', message_text='two')
    fetched = []

    def fetch(_store, url):
        fetched.append(url)
        return {'title': url, 'description': ''}

    monkeypatch.setattr('qq_onebot_whitelist.daily_report.get_or_fetch_link_metadata', fetch)

    build_daily_resource_report(store, enrich_links=True, max_enriched_links=1)

    assert len(fetched) == 1

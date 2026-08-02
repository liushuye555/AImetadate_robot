from qq_onebot_whitelist.daily_report import build_daily_resource_report, canonical_url, dedupe_url_key, should_run_daily_report
from qq_onebot_whitelist.store import Store


def test_build_daily_resource_report_empty_still_reports(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert build_daily_resource_report(store) == '今日无新增资源。'


def test_build_daily_resource_report_includes_files_and_links(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_file(scope='group:1', user_id='u1', file_name='a.zip', file_size=2048, url='u', kind='archive', raw={})
    store.record_link(scope='group:1', user_id='u2', url='https://github.com/a/b', message_text='这个节点', kind='github_project')
    report = build_daily_resource_report(store)
    assert report is not None
    assert 'a.zip' in report
    assert 'github.com/a/b' in report
    assert 'group:1' in report


def test_link_report_omits_source_and_keeps_unknown_link(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:987654', user_id='u', url='https://unknown.example/item')

    report = build_daily_resource_report(store)

    assert 'https://unknown.example/item' in report
    assert '群聊未说明用途' in report
    assert '987654' not in report


def test_canonical_url_removes_trackers_but_keeps_resource_identity():
    assert canonical_url('https://music.163.com/song?id=1&uct2=session') == 'https://music.163.com/song?id=1'
    assert canonical_url('https://zhaiqi.vip/tools/#meme-generator') == 'https://zhaiqi.vip/tools/#meme-generator'
    assert canonical_url('https://www.bilibili.com/video/BV1x/?share_source=copy_web&vd_source=token') == 'https://www.bilibili.com/video/BV1x'


def test_dedupe_url_key_keeps_distinct_query_resources():
    assert dedupe_url_key('https://music.163.com/song?id=1') != dedupe_url_key('https://music.163.com/song?id=2')


def test_should_run_daily_report_in_20_to_21_window_and_once():
    assert should_run_daily_report(hour=20, already_sent=False) is True
    assert should_run_daily_report(hour=19, already_sent=False) is False
    assert should_run_daily_report(hour=21, already_sent=False) is False
    assert should_run_daily_report(hour=20, already_sent=True) is False

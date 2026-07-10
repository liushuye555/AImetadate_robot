from qq_onebot_whitelist.daily_report import build_daily_resource_report, should_run_daily_report
from qq_onebot_whitelist.store import Store


def test_build_daily_resource_report_empty_returns_none(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert build_daily_resource_report(store) is None


def test_build_daily_resource_report_includes_files_and_links(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_file(scope='group:1', user_id='u1', file_name='a.zip', file_size=2048, url='u', kind='archive', raw={})
    store.record_link(scope='group:1', user_id='u2', url='https://github.com/a/b', message_text='这个节点', kind='github_project')
    report = build_daily_resource_report(store)
    assert report is not None
    assert 'a.zip' in report
    assert 'github.com/a/b' in report


def test_should_run_daily_report_in_20_to_21_window_and_once():
    assert should_run_daily_report(hour=20, already_sent=False) is True
    assert should_run_daily_report(hour=19, already_sent=False) is False
    assert should_run_daily_report(hour=21, already_sent=False) is False
    assert should_run_daily_report(hour=20, already_sent=True) is False

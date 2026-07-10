from qq_onebot_whitelist.daily_report import build_daily_resource_report
from qq_onebot_whitelist.store import Store


def test_daily_report_uses_since_time_dedupes_and_filters_low_value_links(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/J7sMUhrZ', message_text='玩了游戏就有无限番茄酱了吗？ 快手极速版')
    store.record_link(scope='group:1', user_id='u1', url='https://civitai.com/models/123/model', message_text='这个 lora 效果不错')
    store.record_link(scope='group:1', user_id='u2', url='https://civitai.com/models/123/model?utm=abc', message_text='重复发一下')
    store.record_link(scope='group:1', user_id='u2', url='https://weird-tools.example/paint', message_text='神奇小网站，可以在线试试效果')
    store.record_file(scope='group:1', user_id='u3', file_name='ANIMA SAM3 修脚套件.json', file_size=12345, url='https://very.long/download/url', kind='workflow', raw={})

    report = build_daily_resource_report(store, since='1970-01-01 00:00:00')

    assert report is not None
    assert 'group:1' in report
    assert '快手' not in report
    assert 'v.kuaishou.com' not in report
    assert report.count('civitai.com/models/123/model') == 1
    assert 'weird-tools.example/paint' in report
    assert '用途：值得一看' in report
    assert '神奇小网站' in report
    assert 'ANIMA SAM3 修脚套件.json' in report
    assert 'https://very.long/download/url' not in report
    assert '简介：新增 1 个文件/工作流、2 条高价值链接' in report


def test_daily_report_redacts_keys_from_link_context(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://github.com/a/b', message_text='测试 key sk-abcdefghijklmnopqrstuvwxyz')

    report = build_daily_resource_report(store, since='1970-01-01 00:00:00')

    assert 'sk-abcdefghijklmnopqrstuvwxyz' not in report
    assert '[已脱敏密钥]' in report


def test_daily_report_returns_none_when_no_valuable_incremental_items(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/J7sMUhrZ', message_text='快手极速版')

    assert build_daily_resource_report(store, since='1970-01-01 00:00:00') is None

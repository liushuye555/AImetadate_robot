from qq_onebot_whitelist.commands import build_reply
from qq_onebot_whitelist.settings import read_analysis_windows
from qq_onebot_whitelist.store import Store


def private_event(text: str) -> dict:
    return {'message_type': 'private', 'user_id': 1, 'message': text}


def group_event(text: str) -> dict:
    return {'message_type': 'group', 'group_id': 2, 'user_id': 1, 'message': text}


def test_private_user_can_view_set_and_clear_analysis_windows(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('ai_context:\n  allowed_windows: []\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')

    assert build_reply(private_event('分析时段 查看'), store, config_path=config) == '当前允许分析时段：全天'
    reply = build_reply(private_event('分析时段 设置 00:30-08:30,12:00-13:00'), store, config_path=config)
    assert '已设置分析时段' in reply
    assert read_analysis_windows(config) == ['00:30-08:30', '12:00-13:00']
    assert '全天' in build_reply(private_event('分析时段 全天'), store, config_path=config)
    assert read_analysis_windows(config) == []


def test_group_cannot_change_analysis_windows(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('{}\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')

    assert build_reply(group_event('分析时段 全天'), store, config_path=config) == '分析时段只能由白名单用户私聊修改。'


def test_slash_prefix_remains_compatible(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('{}\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')

    assert '当前允许分析时段' in build_reply(private_event('/分析时段 查看'), store, config_path=config)

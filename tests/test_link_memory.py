"""站点多功能记忆：画像聚合、确定性判定、资源页免 LLM/分类兜底。"""

from qq_onebot_whitelist.resources import deterministic_category, domain_profiles
from qq_onebot_whitelist.resource_view import select_resource_links
from qq_onebot_whitelist.store import Store


def test_domain_profiles_groups_by_domain_and_function(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://music.163.com/song/1', message_text='分享一首歌')
    store.record_link(scope='group:1', user_id='u', url='https://music.163.com/playlist/2', message_text='歌单')
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV1', message_text='视频')
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV2', message_text='模型训练教程')

    profiles = domain_profiles(store)
    assert profiles['music.163.com']['音乐'] == 2
    assert set(profiles['bilibili.com']) == {'娱乐视频', 'AI模型'}  # 多功能 → 多标签


def test_deterministic_category_rules():
    assert deterministic_category({'音乐': 5, '电台': 1}) == '音乐'
    assert deterministic_category({'音乐': 1, '电台': 1}) is None
    assert deterministic_category({'娱乐视频': 4, '教程': 1}) is None
    assert deterministic_category({'其他': 3}) is None
    assert deterministic_category({}) is None
    assert deterministic_category(None) is None


def test_deterministic_domain_skips_llm_and_classifies_directly(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    for i in range(3):
        store.record_link(scope='group:1', user_id='u', url=f'https://music.163.com/song/{i}', message_text='分享歌曲')
    store.record_link(scope='group:1', user_id='u', url='https://music.163.com/album/9', message_text='', kind='link')

    calls = {'n': 0}

    def fake_judge(url, context):
        calls['n'] += 1
        return '核心AI资源', 1

    monkeypatch.setattr('qq_onebot_whitelist.resource_view.llm_judge_link', fake_judge)
    links = select_resource_links(store, mode='llm')
    assert len(links) == 4
    assert all(link['category'] == '音乐' for link in links)
    assert calls['n'] == 0  # 确定站点绝不调 LLM


def test_mixed_domain_still_judges_per_link(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV1', message_text='看这个视频')
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV2', message_text='模型训练教程')
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV3', message_text='随便看看')

    calls = {'n': 0}

    def fake_judge(url, context):
        calls['n'] += 1
        return '值得一看', 10

    monkeypatch.setattr('qq_onebot_whitelist.resource_view.llm_judge_link', fake_judge)
    links = select_resource_links(store, mode='llm')
    assert calls['n'] == 3  # 混合站点逐条 LLM
    assert len(links) == 3


def test_domain_memory_falls_back_category(tmp_path):
    store = Store(tmp_path / 'bot.db')
    for i in range(3):
        store.record_link(scope='group:1', user_id='u', url=f'https://docs.example.com/{i}', message_text='使用教程')
    store.record_link(scope='group:1', user_id='u', url='https://docs.example.com/x', message_text='')

    links = select_resource_links(store)
    assert all(link['category'] == '教程' for link in links)

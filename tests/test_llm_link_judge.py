"""链接用途 LLM 判定测试。"""

from __future__ import annotations

import json

from qq_onebot_whitelist import llm_link_judge
from qq_onebot_whitelist.llm_link_judge import reset_cost_log
from qq_onebot_whitelist.resource_view import select_resource_links
from qq_onebot_whitelist.store import Store


def test_llm_judge_link_parses_purpose(tmp_path, monkeypatch):
    def fake_llm(url, context):
        return '核心AI资源', 120

    monkeypatch.setattr(llm_link_judge, 'llm_judge_link', fake_llm)
    purpose, tokens = llm_link_judge.llm_judge_link('https://bilibili.com/video/x', '标题：AI 绘图演示')
    assert purpose == '核心AI资源'
    assert tokens == 120


def test_select_resource_links_llm_mode_rescues_media_link(tmp_path, monkeypatch):
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV1x',
                      message_text='【吉尔伽美什，家里进狼了】', kind='link')

    def fake_judge(url, context):
        return '核心AI资源', 50

    monkeypatch.setattr('qq_onebot_whitelist.resource_view.llm_judge_link', fake_judge)
    links = select_resource_links(store, mode='llm')
    assert len(links) == 1
    assert links[0]['purpose'] == '核心AI资源'
    # 缓存生效：第二次不再调用 LLM
    calls = {'n': 0}

    def fake_judge2(url, context):
        calls['n'] += 1
        return '', 0

    monkeypatch.setattr('qq_onebot_whitelist.resource_view.llm_judge_link', fake_judge2)
    links2 = select_resource_links(store, mode='llm')
    assert len(links2) == 1
    assert calls['n'] == 0
    from qq_onebot_whitelist.daily_report import dedupe_url_key
    assert store.get_link_judge(dedupe_url_key('https://www.bilibili.com/video/BV1x')) == '核心AI资源'


def test_select_resource_links_rule_mode_filters_media_link(tmp_path):
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    store.record_link(scope='group:1', user_id='u', url='https://www.bilibili.com/video/BV1x',
                      message_text='【吉尔伽美什，家里进狼了】', kind='link')
    links = select_resource_links(store, mode='rule')
    assert links == []

from datetime import datetime, timezone

from qq_onebot_whitelist.knowledge_view import render_views


class Profile:
    settings = {'lifecycle': {'brief_days': 3, 'detailed_days': 14,
                              'transient_days': 3, 'resource_days': 30}}

    def __init__(self, enabled=True):
        self.enabled = enabled

    def option_enabled(self, section, key):
        return self.enabled and section == 'lifecycle' and key == 'enabled'


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _render(tmp_path, *, items=(), threads=(), profiles=None, manual_archives=None):
    return render_views(tmp_path, items=list(items), runs=[], assets=[], glossary=[],
                        threads=list(threads), profiles=profiles,
                        manual_archives=manual_archives, now=NOW)['knowledge.html']


def test_knowledge_page_has_lane_topic_and_all_category_filters_and_keeps_term_js(tmp_path):
    html = _render(tmp_path)
    assert '<select id="lane"><option value="knowledge">知识</option>' in html
    assert '<option value="followup">待跟进</option>' in html
    assert '<option value="archive">归档</option>' in html
    assert '<option value="">全部类型</option>' in html
    assert '<select id="topic"><option value="">全部情形</option>' in html
    assert "variants.forEach(item=>" in html
    assert "item.dataset.inference===k" in html


def test_lanes_topics_expiry_and_manual_override_render_on_cards(tmp_path):
    items = [
        {'key': 'know', 'scope': 'group:1', 'title': '可复用', 'body': '指南',
         'created_at': '2026-10-01', 'evidence_ids': [1], 'category': 'knowledge',
         'source_time': '1970-01-01T00:00:00Z',
         'organization': {'topics': ['development'], 'subject': {'ambiguous': True}}},
        {'key': 'question', 'scope': 'group:1', 'title': '未解决问题', 'body': '求助',
         'created_at': '2026-10-01', 'evidence_ids': [2], 'category': 'question',
         'evidence_state': 'unresolved', 'source_time': '2020-01-01T00:00:00Z',
         'organization': {'topics': ['accounts']}},
        {'key': 'resource', 'scope': 'group:1', 'title': '资源线索', 'body': '链接',
         'created_at': '2026-10-01', 'evidence_ids': [3], 'category': 'resource',
         'source_time': '2020-01-01T00:00:00Z', 'organization': {'topics': ['resources']}},
    ]
    html = _render(tmp_path, items=items, profiles={'group:1': Profile()},
                   manual_archives={('group:1', 'item', 'know'): {'state': 'archived', 'reason': 'manual'}})
    assert 'data-lane="archive" data-topics="development"' in html
    assert 'data-lane="archive" data-topics="accounts"' in html
    assert 'data-lane="archive" data-topics="resources"' in html
    assert '人工归档；归档不代表问题已解决。' in html
    assert '对象指代待确认' in html
    assert '保留截止时间：' in html


def test_default_off_separates_followup_without_auto_archiving(tmp_path):
    items = [
        {'key': 'knowledge', 'scope': 'group:1', 'title': '知识', 'body': '正文',
         'evidence_ids': [1], 'category': 'knowledge', 'source_time': '1970-01-01T00:00:00Z'},
        {'key': 'question', 'scope': 'group:1', 'title': '求助', 'body': '未解决',
         'evidence_ids': [2], 'category': 'question', 'evidence_state': 'unresolved',
         'source_time': '1970-01-01T00:00:00Z'},
        {'key': 'transient', 'scope': 'group:1', 'title': '时效信息', 'body': '过时',
         'evidence_ids': [3], 'category': 'transient', 'source_time': '1970-01-01T00:00:00Z'},
    ]
    html = _render(tmp_path, items=items)
    assert 'data-lane="knowledge" data-topics="other"' in html
    assert 'data-lane="followup" data-topics="other"' in html
    assert 'data-lane="archive"' not in html


def test_thread_event_uses_item_organization_and_topic_union(tmp_path):
    item = {'key': 'item-1', 'scope': 'group:1', 'title': '更新', 'body': '新内容',
            'evidence_ids': [8], 'category': 'knowledge', 'organization': {'topics': ['development']}}
    thread = {'id': 'topic-1', 'scope': 'group:1', 'title': '讨论', 'status': 'open',
              'category': 'question', 'evidence_ids': [8], 'events': [
                  {'item_key': 'item-1', 'source_time': '2026-10-10T00:00:00Z',
                   'summary': '有新的排查结果', 'status': 'in_progress', 'category': 'question',
                   'evidence_state': 'reported', 'evidence_ids': [8], 'link_reason': ''}
              ]}
    html = _render(tmp_path, items=[item], threads=[thread], profiles={'group:1': Profile()})
    assert 'data-lane="followup" data-topics="development"' in html
    assert '原消息进展时间：' in html
    assert '保留截止时间：' in html


def test_lane_topic_and_type_filters_execute_together(tmp_path):
    import json
    import re
    import shutil
    import subprocess
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed to execute report filters')
    script = re.search(r'<script id="knowledge-script">(.*?)</script>', _render(tmp_path), re.S).group(1)
    harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const elements={group:{value:''},search:{value:''},lane:{value:'knowledge'},topic:{value:''},category:{value:''},'filter-empty':{},'shown-count':{}};
for(const e of Object.values(elements))e.addEventListener=()=>{};
const cards=[{dataset:{lane:'knowledge',topics:'development,model_usage',category:'knowledge'},textContent:'教程'},
{dataset:{lane:'followup',topics:'accounts',category:'question'},textContent:'封禁待确认'},
{dataset:{lane:'archive',topics:'accounts,model_usage',category:'question'},textContent:'过期求助'}];
const context={document:{getElementById:id=>elements[id],querySelectorAll:()=>cards}};
vm.createContext(context);vm.runInContext(fs.readFileSync(0,'utf8'),context);
assert.deepEqual(cards.map(c=>c.hidden),[false,true,true]);
elements.lane.value='';elements.topic.value='accounts';context.filterRows();
assert.deepEqual(cards.map(c=>c.hidden),[true,false,false]);
elements.lane.value='archive';elements.category.value='question';context.filterRows();
assert.deepEqual(cards.map(c=>c.hidden),[true,true,false]);assert.equal(elements['shown-count'].textContent,1);
elements.search.value='missing';context.filterRows();assert.equal(elements['filter-empty'].hidden,false);
'''
    result = subprocess.run([node, '-e', harness], input=script, text=True, encoding='utf-8',
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

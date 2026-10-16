import re
import shutil
import subprocess

import pytest

from qq_onebot_whitelist.knowledge_view import render_views


def test_deep_links_queue_navigation_paging_and_reset_work_together(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed for report interaction tests')
    html = render_views(tmp_path, items=[], runs=[], assets=[], glossary=[])['knowledge.html']
    script = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
    harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
function element(value=''){return {value,events:{},addEventListener(name,fn){this.events[name]=fn;},focus(){this.focused=true;},setAttribute(name,value){this[name]=value;}};}
const e={group:element(),search:element(),lane:element('knowledge'),topic:element(),category:element(),value:element(),'filter-empty':{},'shown-count':{},'page-info':{},'previous-page':element(),'next-page':element(),'clear-filters':element(),results:{scrollIntoView(){}}};
const queueButtons=['knowledge','followup','archive',''].map(lane=>({...element(),dataset:{laneTarget:lane}}));
const cards=Array.from({length:42},(_,i)=>({dataset:{group:'A',lane:i<25?'knowledge':'followup',topics:'accounts',category:i<25?'knowledge':'question'},textContent:'item '+i,hidden:false}));
const events={};const window={location:{hash:'#followup'},addEventListener(name,fn){events[name]=fn;}};
const context={window,document:{getElementById:id=>e[id]||null,querySelectorAll:selector=>selector==='article'?cards:selector==='[data-lane-target]'?queueButtons:[],addEventListener(){}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(0,'utf8'),context);
assert.equal(e.lane.value,'followup');assert.equal(e['shown-count'].textContent,17);assert.equal(cards.filter(c=>!c.hidden).length,17);
queueButtons[0].events.click();assert.equal(window.location.hash,'knowledge');assert.equal(e['shown-count'].textContent,25);assert.equal(cards.filter(c=>!c.hidden).length,20);
e['next-page'].events.click();assert.equal(cards.filter(c=>!c.hidden).length,5);assert.equal(e['page-info'].textContent,'2 / 2 页');
e.search.value='item 1';e.search.events.input();assert.equal(cards.filter(c=>!c.hidden).length,11);assert.equal(e['page-info'].textContent,'1 / 1 页');
e.topic.value='missing';e.topic.events.change();assert.equal(e['shown-count'].textContent,0);assert.equal(e['filter-empty'].hidden,false);
e['clear-filters'].events.click();assert.equal(e.lane.value,'knowledge');assert.equal(e.topic.value,'');assert.equal(e.search.value,'');assert.equal(e['shown-count'].textContent,25);
window.location.hash='#all';events.hashchange();assert.equal(e['shown-count'].textContent,42);
window.location.hash='';events.hashchange();assert.equal(e.lane.value,'knowledge');assert.equal(queueButtons[0]['aria-pressed'],'true');
'''
    result = subprocess.run([node, '-e', harness], input=script, text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_report_hierarchy_keeps_search_details_and_local_navigation(tmp_path):
    pages = render_views(tmp_path, items=[{'key': 'k', 'title': '<img onerror=alert(1)>',
        'body': 'a' * 400, 'scope': 'group:1', 'category': 'knowledge'}], runs=[], assets=[], glossary=[])
    html = pages['knowledge.html']
    assert 'aria-label="资料处理队列"' in html
    assert 'data-lane-target="followup"' in html and 'class="queue-count"' in html
    assert 'class="more-filters"' in html and 'id="next-page"' in html
    assert 'class="card-excerpt"' in html and '查看完整内容与依据' in html
    assert '<img onerror=' not in html
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', html)


def test_excerpt_redacts_before_truncation_can_cut_through_a_credential(tmp_path):
    value = 'x ' * 111 + ' wb-' + 'a' * 64
    html = render_views(tmp_path, items=[{'title': '测试', 'body': value}], runs=[], assets=[], glossary=[])['knowledge.html']
    assert 'wb-aaa' not in html

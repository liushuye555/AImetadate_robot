import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from qq_onebot_whitelist import knowledge_view


def test_views_keep_the_four_content_types_separate_and_navigate(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, "render_evidence", lambda *_: "<details><summary>来源 #7</summary></details>")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_controls", lambda *_: "<div class='feedback'>纠错</div>")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_token", lambda *_: "safe-token")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_script", lambda _: "<div id='missed-feedback'>漏收</div>")
    views = knowledge_view.render_views(
        tmp_path,
        items=[{"key": "k", "scope": "群A", "title": "知识项", "body": "知识正文", "value": "high",
                "evidence_ids": [7], "evidence_state": "verified"}],
        glossary=[{"scope": "群A", "term": "术语项", "meaning": "仅属于术语卡的内容", "origin": "user", "status": "active",
                   "evidence_ids": [7]}],
        runs=[{"scope": "群A", "kind": "daily", "created_at": "2026-10-15", "result": {
            "input_count": 4, "summary": [{"text": "总结正文", "evidence_ids": [7]}]}}],
        assets=[{"scope": "群A", "name": "文件项", "status": "saved", "message_id": 7, "path": "local/file"}],
    )
    assert set(views) == {"knowledge.html", "glossary.html", "knowledge-summary.html", "knowledge-files.html"}
    assert "知识正文" in views["knowledge.html"] and "仅属于术语卡的内容" not in views["knowledge.html"]
    assert "总结正文" not in views["knowledge.html"] and "文件项" not in views["knowledge.html"]
    assert "仅属于术语卡的内容" in views["glossary.html"] and "知识正文" not in views["glossary.html"]
    assert "总结正文" in views["knowledge-summary.html"] and "知识正文" not in views["knowledge-summary.html"]
    assert "文件项" in views["knowledge-files.html"] and "知识正文" not in views["knowledge-files.html"]
    for filename, html in views.items():
        for target in views:
            assert f'href="{target}"' in html
        assert f'href="{filename}" aria-current="page"' in html
        assert "id=\"group\"" in html and "id=\"search\"" in html
    assert "feedback" in views["knowledge.html"] and "feedback" not in views["glossary.html"]
    assert "missed-feedback" in views["knowledge.html"] and "missed-feedback" not in views["knowledge-files.html"]


def test_views_escape_user_content_and_provide_empty_states(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, "render_evidence", lambda *_: "<details></details>")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_token", lambda *_: "token")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_script", lambda _: "")
    views = knowledge_view.render_views(
        tmp_path,
        items=[{"scope": "<img src=x onerror=alert(1)>", "title": "<script>alert(1)</script>",
                "body": "api_key=abcdefghijklmnopqrstuvwxyz0123456789", "value": "candidate", "evidence_ids": []}],
        runs=[], assets=[], glossary=[])
    assert "<script>alert(1)</script>" not in views["knowledge.html"]
    assert "&lt;script&gt;" in views["knowledge.html"]
    assert "<img src=x" not in views["knowledge.html"]
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in views["knowledge.html"]
    for filename in ("glossary.html", "knowledge-summary.html", "knowledge-files.html"):
        assert "本页暂无正式资料。" in views[filename]


@pytest.mark.parametrize('filename', ['knowledge.html', 'glossary.html', 'knowledge-summary.html', 'knowledge-files.html'])
def test_generated_filters_run_for_each_page(tmp_path, monkeypatch, filename):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed to run report filters')
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_feedback.feedback_token', lambda *_: 'test-token')
    page = knowledge_view.render_views(tmp_path, items=[], runs=[], assets=[], glossary=[])[filename]
    script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
    harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements={group:{value:''},search:{value:''},'filter-empty':{hidden:true}};
if(input.filename==='knowledge.html')elements.value={value:''};
if(input.filename==='knowledge.html')elements.category={value:'durable'};
if(input.filename==='glossary.html')elements['term-status']={value:''};
if(input.filename==='glossary.html')elements['term-kind']={value:''};
for(const element of Object.values(elements))element.addEventListener=()=>{};
const cards=[{dataset:{group:'A',value:'high',status:'active',origin:'ai',inference:'explicit'},textContent:'Alpha',hidden:false},
 {dataset:{group:'B',value:'candidate',status:'candidate',origin:'ai',inference:'inferred'},textContent:'Beta',hidden:false}];
const context={document:{getElementById:id=>elements[id]||null,querySelectorAll:()=>cards}};
vm.createContext(context);vm.runInContext(input.script,context);
context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[false,false]);
if(elements.category){cards.push({dataset:{group:'A',category:'transient'},textContent:'Service status',hidden:false});context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[false,false,true]);elements.category.value='transient';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[true,true,false]);elements.category.value='durable';cards.pop();}
elements.group.value='A';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[false,true]);
elements.group.value='';elements.search.value='beta';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[true,false]);
elements.search.value='missing';context.filterRows();assert.equal(elements['filter-empty'].hidden,false);
elements.search.value='';
if(elements.value){elements.value.value='candidate';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[true,false]);}
if(elements['term-status']){elements['term-status'].value='active';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[false,true]);}
if(elements['term-kind']){elements['term-status'].value='';elements['term-kind'].value='inferred';context.filterRows();assert.deepEqual(cards.map(c=>c.hidden),[true,false]);}
'''
    completed = subprocess.run([node, '-e', harness], input=json.dumps({'filename': filename, 'script': script}),
                               text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert completed.returncode == 0, completed.stderr

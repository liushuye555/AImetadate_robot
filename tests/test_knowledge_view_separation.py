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


def test_saved_file_actions_are_local_group_scoped_and_encoded(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_feedback.feedback_token', lambda *_: 'test-token')
    data_dir = tmp_path / 'data'
    own_dir = data_dir / 'knowledge-files' / '123'
    other_dir = data_dir / 'knowledge-files' / '999'
    own_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    own_file = own_dir / '资料 文件#1.pdf'
    other_file = other_dir / 'other.pdf'
    outside_file = tmp_path / 'outside.pdf'
    for path in (own_file, other_file, outside_file):
        path.write_bytes(b'local-test')
    views = knowledge_view.render_views(data_dir, items=[], glossary=[], runs=[], assets=[
        {'scope': 'group:123', 'name': '报告 "最终版" & <附件>.pdf', 'status': 'saved', 'path': str(own_file)},
        {'scope': 'group:123', 'name': '越界文件.pdf', 'status': 'saved', 'path': str(outside_file)},
        {'scope': 'group:123', 'name': '别群文件.pdf', 'status': 'saved', 'path': str(other_file)},
        {'scope': 'group:123', 'name': '失败文件.pdf', 'status': 'failed', 'path': str(own_file)},
    ])

    page = views['knowledge-files.html']
    expected_href = '../knowledge-files/123/%E8%B5%84%E6%96%99%20%E6%96%87%E4%BB%B6%231.pdf'
    action_blocks = re.findall(r'<p class="actions">(.*?)</p>', page, re.S)
    assert len(action_blocks) == 1
    assert action_blocks[0].count('href="' + expected_href + '"') == 2
    assert 'download="报告 &quot;最终版&quot; &amp; &lt;附件&gt;.pdf"' in page
    assert 'outside.pdf' not in action_blocks[0] and '999/other.pdf' not in action_blocks[0]
    assert 'failed.pdf' not in action_blocks[0]


def test_file_status_and_recovery_errors_are_rendered_in_chinese(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_feedback.feedback_token', lambda *_: 'test-token')
    views = knowledge_view.render_views(tmp_path, items=[], glossary=[], runs=[], assets=[
        {'scope': 'group:123', 'name': 'a.pdf', 'status': 'saved'},
        {'scope': 'group:123', 'name': 'b.pdf', 'status': 'failed', 'error': 'FileReferenceUnavailable'},
        {'scope': 'group:123', 'name': 'c.pdf', 'status': 'failed', 'error': 'AmbiguousFileReference'},
        {'scope': 'group:123', 'name': 'd.pdf', 'status': 'pending'},
    ])

    page = views['knowledge-files.html']
    assert '已保存' in page and '保存失败' in page and '待保存' in page
    assert '旧文件引用已失效，群文件列表中未找到匹配。' in page
    assert '群内存在同名同大小文件，无法安全确认对应文件。' in page


@pytest.mark.parametrize('filename', ['knowledge.html', 'glossary.html', 'knowledge-summary.html', 'knowledge-files.html'])
def test_generated_filters_run_for_each_page(tmp_path, monkeypatch, filename):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed to run report filters')
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_feedback.feedback_token', lambda *_: 'test-token')
    page = knowledge_view.render_views(tmp_path, items=[], runs=[], assets=[], glossary=[])[filename]
    script = re.search(r'<script id="knowledge-script">(.*?)</script>', page, re.S).group(1)
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

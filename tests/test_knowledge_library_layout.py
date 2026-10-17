"""Layout contracts for the shared local resource and knowledge libraries."""
import re
import json
import shutil
import subprocess
from html.parser import HTMLParser

from qq_onebot_whitelist import knowledge_view
from qq_onebot_whitelist.view_theme import (
    BASE_CSS,
    THEME_INIT_JS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_JS,
)


def _page(tmp_path, monkeypatch, *, item=None):
    monkeypatch.setattr(knowledge_view, "render_evidence", lambda *_: "")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_token", lambda *_: "test-token")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_script", lambda _: "")
    return knowledge_view.render_views(
        tmp_path, items=[item] if item else [], runs=[], assets=[], glossary=[]
    )["knowledge.html"]


def test_knowledge_page_reuses_shared_theme_and_returns_to_library_index(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)

    assert BASE_CSS in page
    assert THEME_INIT_JS in page
    assert THEME_TOGGLE_HTML in page
    assert THEME_TOGGLE_JS in page
    assert re.search(r'<a\b[^>]*class="brand"[^>]*href="index\.html"', page)
    assert "返回资料总览" in page


def test_subject_directory_is_collapsible_and_has_its_own_search(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch, item={
        "key": "directory-case", "scope": "群A", "title": "主题条目",
        "body": "原文内容", "value": "high",
        "organization": {"subjects": [{"name": "虚拟卡"}]},
    })

    assert re.search(r'<details\b[^>]*id="subject-directory"', page)
    assert re.search(r'<input\b[^>]*id="subject-search"', page)


def test_category_and_usage_evidence_stay_in_card_details_without_repeated_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, "usage_for", lambda *_: [{
        "subject": "虚拟卡", "tag": "armor_tool", "origin": "source",
        "evidence": [{"message_id": 12, "quote": "虚拟卡用于破甲工具"}],
    }])
    page = _page(tmp_path, monkeypatch, item={
        "key": "compact-case", "scope": "群A", "title": "虚拟卡接入",
        "body": "保留这段原文：额度为 500 元。", "value": "high",
        "organization": {
            "subjects": [{"name": "虚拟卡"}],
            "topic_tags": [{"name": "闲鱼", "evidence": [
                {"message_id": 12, "quote": "原文提及闲鱼"}
            ]}],
        },
    })
    class CardDetailParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.card_details = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            capture = None
            if tag == "details" and "card-details" in (attrs.get("class") or "").split():
                capture = []
                self.card_details.append(capture)
            self.stack.append((tag, capture))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_data(self, data):
            for _, capture in self.stack:
                if capture is not None:
                    capture.append(data)

    parser = CardDetailParser()
    parser.feed(page)
    details = ["".join(section) for section in parser.card_details]

    assert details, "the knowledge card should provide a dedicated details section"
    assert any("分类依据" in section or "主题归类依据" in section for section in details)
    assert any("用途标签依据" in section and "虚拟卡用于破甲工具" in section for section in details)
    assert "涉及对象/资料主题：" not in page
    assert "保留这段原文：额度为 500 元。" in page
    assert "原文提及闲鱼" in page
    assert "&lt;script&gt;" not in page


def test_card_content_remains_escaped_and_visible_after_layout_compaction(tmp_path, monkeypatch):
    original = "内容包含 <标签> & 符号，且原句需要保留。"
    page = _page(tmp_path, monkeypatch, item={
        "key": "escaped-case", "scope": "群A", "title": "安全展示",
        "body": original, "value": "candidate",
    })

    assert original not in page
    assert "内容包含 &lt;标签&gt; &amp; 符号，且原句需要保留。" in page


def test_subject_search_is_independent_and_clear_filters_resets_it(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("Node.js is needed to run directory search")
    page = _page(tmp_path, monkeypatch, item={
        "key": "directory-case", "scope": "群A", "title": "主题条目",
        "body": "正文关键词", "value": "high",
        "organization": {"subjects": [{"name": "Alpha"}, {"name": "Beta"}]},
    })
    script = re.search(r'<script id="knowledge-script">(.*?)</script>', page, re.S).group(1)
    harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const script=JSON.parse(fs.readFileSync(0,'utf8'));
function field(value=''){return {value,hidden:false,listeners:{},addEventListener(k,f){this.listeners[k]=f},focus(){}}}
const elements={group:field(''),search:field(''),subject:field('Beta'),'subject-search':field(''),
 'filter-empty':field(),'shown-count':field(),'page-info':field(),'clear-filters':field(),
 'subject-search-empty':field(),lane:field('knowledge')};
const subjects=['', 'Alpha','Beta'].map((name)=>({dataset:{subjectTarget:name,subjectName:name||'全部主题'},hidden:false,
 listeners:{},addEventListener(k,f){this.listeners[k]=f},setAttribute(){},querySelector(){return null}}));
const cards=[{dataset:{group:'群A',subjects:'Alpha,Beta',subject:'Alpha',subjectName:'Alpha / Beta',category:'knowledge',lane:'knowledge',topics:'other'},
 textContent:'正文关键词',hidden:false,querySelectorAll(){return []}}];
const doc={getElementById:id=>elements[id]||null,
 querySelectorAll(sel){if(sel==='article')return cards;if(sel==='[data-subject-target]')return subjects;if(sel==='[data-lane-target]')return [];if(sel==='.subject-section')return [];return []},
 addEventListener(){}};
const context={document:doc};vm.createContext(context);vm.runInContext(script,context);
elements['subject-search'].value='alpha';elements['subject-search'].listeners.input();
assert.deepEqual(subjects.map(x=>x.hidden),[false,false,true]);
assert.equal(elements.subject.value,'Beta');assert.equal(cards[0].hidden,false);
elements.group.value='群A';elements.search.value='正文关键词';elements['clear-filters'].listeners.click();
assert.equal(elements['subject-search'].value,'');assert.deepEqual(subjects.map(x=>x.hidden),[false,false,false]);
assert.equal(elements.subject.value,'');assert.equal(elements.group.value,'');assert.equal(elements.search.value,'');
assert.equal(cards[0].hidden,false);
'''
    completed = subprocess.run([node, "-e", harness], input=json.dumps(script), text=True,
                               encoding="utf-8", capture_output=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


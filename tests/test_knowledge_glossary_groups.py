import json
import re
import shutil
import subprocess

import pytest

from qq_onebot_whitelist import knowledge_view
from qq_onebot_whitelist.knowledge_glossary_groups import group_glossary


def test_same_term_keeps_distinct_meanings_and_combines_identical_ones():
    rows = [
        {"scope": "群A", "term": " StarFlow ", "meaning": "生成图像", "status": "active", "origin": "ai",
         "evidence_ids": [1], "inference_kind": "inferred", "inference_note": "上下文", "inference_evidence": [{"message_id": 1, "quote": "StarFlow 生成图像"}]},
        {"scope": "群A", "term": "starflow", "meaning": " 生成图像 ", "status": "candidate", "origin": "ai",
         "evidence_ids": [2], "inference_kind": "unconfirmed", "inference_evidence": []},
        {"scope": "群A", "term": "STARFLOW", "meaning": "游戏里的流派", "status": "candidate", "origin": "ai",
         "evidence_ids": [3], "inference_kind": "ambiguous", "inference_note": "仍有分歧"},
    ]
    groups = group_glossary(rows)
    assert len(groups) == 1
    assert len(groups[0]["variants"]) == 2
    image, game = groups[0]["variants"]
    assert image["status"] == "candidate"
    assert image["evidence_ids"] == [1, 2]
    assert image["inference_kind"] == "unconfirmed"
    assert game["meaning"] == "游戏里的流派" and game["inference_kind"] == "ambiguous"


def test_term_normalization_does_not_merge_across_scopes_or_upgrade_candidates():
    groups = group_glossary([
        {"scope": "群A", "term": "Ａ B", "meaning": "解释甲", "status": "candidate", "origin": "ai"},
        {"scope": "群B", "term": "a b", "meaning": "解释甲", "status": "candidate", "origin": "ai"},
    ])
    assert len(groups) == 2
    assert all(group["variants"][0]["status"] == "candidate" for group in groups)


def test_manual_meaning_wins_for_identical_definition():
    groups = group_glossary([
        {"scope": "群A", "term": "词", "meaning": "人工确认释义", "status": "active", "origin": "user"},
        {"scope": "群A", "term": "词", "meaning": "人工确认释义", "status": "candidate", "origin": "ai"},
    ])
    variant = groups[0]["variants"][0]
    assert variant["origin"] == "user" and variant["status"] == "active"


def test_technical_meaning_case_is_significant_and_does_not_merge_evidence():
    groups = group_glossary([
        {"scope": "Group A", "term": "rate", "meaning": "MB/s", "origin": "user", "status": "active",
         "evidence_ids": [10]},
        {"scope": "Group A", "term": "RATE", "meaning": "Mb/s", "origin": "ai", "status": "candidate",
         "evidence_ids": [11]},
    ])
    variants = groups[0]["variants"]
    assert len(variants) == 2
    assert variants[0]["meaning"] == "MB/s" and variants[0]["evidence_ids"] == [10]
    assert variants[1]["meaning"] == "Mb/s" and variants[1]["status"] == "candidate"
    assert variants[1]["evidence_ids"] == [11]


def test_render_groups_variants_but_status_filter_keeps_matching_meaning(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to run report filters")
    monkeypatch.setattr(knowledge_view, "render_evidence", lambda _dir, _scope, ids: f"<aside>{ids}</aside>")
    page = knowledge_view.render_views(tmp_path, items=[], runs=[], assets=[], glossary=[
        {"scope": "Group A", "term": "term", "meaning": "image generation", "origin": "ai", "status": "candidate",
         "inference_kind": "inferred", "inference_note": "context", "evidence_ids": [1],
         "inference_evidence": [{"message_id": 1, "quote": "term means image generation"}], "aliases": ["term", "validatedAlias"]},
        {"scope": "Group A", "term": " term ", "meaning": "game map", "origin": "ai", "status": "candidate",
         "inference_kind": "unconfirmed", "evidence_ids": [2]},
        {"scope": "Group B", "term": "term", "meaning": "other group meaning", "origin": "ai", "status": "candidate",
         "inference_kind": "unconfirmed", "evidence_ids": [3]},
    ])["glossary.html"]
    assert page.count('data-term-variant="1"') == 3
    assert "term means image generation" in page
    assert page.count("<h2>term</h2>") == 2
    assert "validatedAlias" not in page and "原文别名：term" in page
    script = re.search(r'<script id="knowledge-script">(.*?)</script>', page, re.S).group(1)
    harness = r'''const vm=require('vm'),assert=require('assert/strict');
const elements={group:{value:''},search:{value:''},'term-status':{value:'active'},'term-kind':{value:''},'filter-empty':{hidden:true},'shown-count':{textContent:'3'}};
for(const e of Object.values(elements))e.addEventListener=()=>{};
function variant(status,origin='ai',inference='unconfirmed',textContent=''){return {dataset:{status,origin,inference},textContent,hidden:false};}
function card(group,variants,text){return {dataset:{group,termShared:'term Group A'},textContent:text,hidden:false,querySelectorAll:()=>variants};}
const variants=[variant('candidate','ai','inferred','candidateExclusive'),variant('active','user','explicit','manual meaning')];
const cards=[card('Group A',variants,'term image generation game map candidateExclusive manual meaning'),card('Group B',[variant('candidate')],'term other group meaning')];
const context={document:{getElementById:id=>elements[id]||null,querySelectorAll:()=>cards}};vm.createContext(context);vm.runInContext(INPUT,context);
assert.equal(variants[0].hidden,true);assert.equal(variants[1].hidden,false);assert.equal(cards[0].hidden,false);assert.equal(cards[1].hidden,true);assert.equal(elements['shown-count'].textContent,1);
elements.search.value='candidateExclusive';context.filterRows();assert.equal(variants[1].hidden,true);assert.equal(cards[0].hidden,true);
elements.search.value='term';context.filterRows();assert.equal(variants[1].hidden,false);assert.equal(cards[0].hidden,false);
'''.replace("INPUT", json.dumps(script))
    result = subprocess.run([node, "-e", harness], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

import shutil
import subprocess

import pytest

from qq_onebot_whitelist.knowledge_presentation import SCRIPT


def test_subject_navigation_counts_and_sections_follow_filters():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed for report interaction tests')
    harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
function element(value=''){return {value,hidden:false,events:{},dataset:{},addEventListener(name,fn){this.events[name]=fn;},setAttribute(name,value){this[name]=value;},focus(){},querySelector(){return null;},querySelectorAll(){return [];}};}
const e={group:element(),search:element(),subject:element(),'usage-tag':element(),lane:element(),topic:element(),category:element(),value:element(),'filter-empty':element(),'shown-count':element(),'page-info':element(),'previous-page':element(),'next-page':element(),'clear-filters':element(),results:element()};
const cards=[{dataset:{subject:'zhipu',group:'g',lane:'knowledge',topics:'x',category:'knowledge',usageTags:'armor_tool',usageNames:'破甲工具'},textContent:'额度设置',hidden:false,querySelectorAll(){return [];}},{dataset:{subject:'zhipu',group:'g',lane:'knowledge',topics:'x',category:'knowledge',usageTags:'reverse_tool',usageNames:'逆向工具'},textContent:'接入方式',hidden:false,querySelectorAll(){return [];}},{dataset:{subject:'other',group:'g',lane:'knowledge',topics:'x',category:'knowledge',usageTags:'armor_tool,reverse_tool',usageNames:'破甲工具 / 逆向工具'},textContent:'故障处理',hidden:false,querySelectorAll(){return [];}}];
const sections=[{dataset:{subjectGroup:'zhipu'},hidden:false,querySelectorAll(){return cards.slice(0,2);},querySelector(s){return s==='[data-subject-visible-count]'?zBadge:null;}},{dataset:{subjectGroup:'other'},hidden:false,querySelectorAll(){return cards.slice(2);},querySelector(s){return s==='[data-subject-visible-count]'?oBadge:null;}}];
const zBadge=element(),oBadge=element(),zCount=element(),oCount=element();
const subjects=[{...element(),dataset:{subjectTarget:'',subjectName:'全部主题'},querySelector(){return allCount;}},{...element(),dataset:{subjectTarget:'zhipu',subjectName:'智谱'},querySelector(){return zCount;}},{...element(),dataset:{subjectTarget:'other',subjectName:'其他'},querySelector(){return oCount;}}];
const lanes=[];const doc={getElementById:id=>e[id]||null,querySelectorAll:s=>s==='article'?cards:s==='[data-subject-target]'?subjects:s==='.subject-section'?sections:s==='[data-lane-target]'?lanes:[],addEventListener(){}};
const allCount=element();const context={document:doc,window:{location:{hash:'#all'},addEventListener(){}}};vm.createContext(context);vm.runInContext(require('node:fs').readFileSync(0,'utf8'),context);
assert.equal(e['shown-count'].textContent,3);assert.equal(zCount.textContent,2);assert.equal(oCount.textContent,1);assert.equal(allCount.textContent,3);
subjects[1].events.click();assert.equal(e.subject.value,'zhipu');assert.equal(e['shown-count'].textContent,2);assert.equal(cards.filter(c=>!c.hidden).length,2);assert.equal(sections[1].hidden,true);assert.equal(allCount.textContent,3);assert.equal(subjects[1]['aria-pressed'],'true');assert.equal(subjects[0]['aria-pressed'],'false');
e.search.value='额度';e.search.events.input();assert.equal(e['shown-count'].textContent,1);assert.equal(zCount.textContent,1);assert.equal(oCount.textContent,0);assert.equal(zBadge.textContent,'1 条');
e['usage-tag'].value='armor_tool';e['usage-tag'].events.change();assert.equal(e['shown-count'].textContent,1);assert.equal(zCount.textContent,1);assert.equal(oCount.textContent,0);assert.equal(e.subject.value,'zhipu');
e['clear-filters'].events.click();assert.equal(e.subject.value,'');assert.equal(e['usage-tag'].value,'');assert.equal(e['shown-count'].textContent,3);
cards[2].dataset.subjects='other,zhipu';cards[2].dataset.subjectName='其他 / 智谱';
e.subject.value='zhipu';context.filterRows();assert.equal(e['shown-count'].textContent,3);assert.equal(zCount.textContent,3);assert.equal(allCount.textContent,3);assert.equal(sections[1].hidden,false);
cards[0].dataset.subjectName='智谱';cards[1].dataset.subjectName='智谱';e.search.value='破甲工具';context.filterRows();assert.equal(e['shown-count'].textContent,2);assert.equal(zCount.textContent,2);assert.equal(oCount.textContent,1);
e['usage-tag'].value='armor_tool';context.filterRows();assert.equal(e['shown-count'].textContent,2);assert.equal(zCount.textContent,2);assert.equal(oCount.textContent,1);
'''
    result = subprocess.run([node, '-e', harness], input=SCRIPT, text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

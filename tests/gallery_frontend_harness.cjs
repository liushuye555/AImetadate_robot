// Exercise gallery browse, group, viewer and query-state behavior without a browser or network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase(); this.value=''; this.checked=false; this.options=[{value:''}];
    this.children=[]; this.attributes={}; this.listeners={}; this.className=''; this.hidden=false;
    this._text=''; this.src=''; this.href=''; this.disabled=false; this.open=false; this.style={};
    this.complete=false; this.width=0; this.height=0;
    this.classList={add:n=>{if(!this.classList.contains(n))this.className=`${this.className} ${n}`.trim()},remove:n=>{this.className=this.className.split(/\s+/).filter(x=>x&&x!==n).join(' ')},contains:n=>this.className.split(/\s+/).includes(n)};
  }
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('')}
  set textContent(v){this._text=String(v);this.children=[]}
  add(o){this.options.push(o)} remove(i){this.options.splice(i,1)}
  replaceChildren(...c){this.children=c;this._text=''} append(...c){this.children.push(...c)}
  addEventListener(n,f){(this.listeners[n]||=[]).push(f)}
  setAttribute(n,v){this.attributes[n]=String(v)} getAttribute(n){return this.attributes[n]??null}
  removeAttribute(n){delete this.attributes[n];if(n==='src')this.src=''}
  querySelector(s){const m=s.match(/^([a-zA-Z][\w-]*)?(?:\.([\w-]+))?$/);const matches=n=>!!m&&(m[1]?n.tagName.toLowerCase()===m[1].toLowerCase():true)&&(!m[2]||n.classList.contains(m[2]));const walk=n=>{for(const c of n.children){if(matches(c))return c;const x=walk(c);if(x)return x}return null};return walk(this)}
  showModal(){this.open=true} close(){if(!this.open)return;this.open=false;for(const f of this.listeners.close||[])f()}
  click(){const e={target:this,preventDefault(){}};if(this.onclick)this.onclick(e);for(const f of this.listeners.click||[])f(e)}
  getBoundingClientRect(){return {height:220}}
}
const elements=new Map();
const get=s=>{if(!elements.has(s))elements.set(s,new Element(s.startsWith('#')?'div':s));return elements.get(s)};
const viewerStage=get('#viewerStage');viewerStage.append(new Element('img'),get('#viewerPrev'),get('#viewerNext'),get('#viewerStatus'));get('#viewer').append(viewerStage,get('#viewerControls'),get('#viewerInfo'));
get('#viewerInfo').append(get('#viewerDetails'),get('#copyPrompt'));
const fields={};for(const n of ['keyword','category','scope','user','source','orientation','min_side','since','until','sort','dup_only'])fields[n]=new Element('input');
get('#filters').elements=fields;
get('#exportForm').elements={out_dir:new Element('input'),no_captions:new Element('input'),dry_run:new Element('input')};get('#exportForm').elements.dry_run.checked=true;
const image=(id,extra={})=>({id,thumbnail:`/thumb/${id}.jpg`,url:`/image/${id}.jpg`,width:1024,height:768,category:'ai_metadata',ai_source:'sample-tool',seen_at:'2026-11-08T12:00:00',scope:'group:A',user_id:'user-42',text_excerpt:`sample prompt ${id}`,...extra});
const first=image('one',{groups:[{key:'batch-7',kind:'同批',count:2},{key:'similar-4',kind:'相似',count:3}]});
const second=image('two');
const requests=[],keyEvents=[],pendingSlow=[],pendingDetails=[];
const browseResponse=(url)=>{const p=new URL(url,'http://local').searchParams;const term=p.get('keyword');if(term==='slow')return new Promise(resolve=>pendingSlow.push(()=>resolve({items:[image('slow-result')],total:1,group_total:1,has_more:false,page:1})));if(term==='fast')return {items:[image('fast-result')],total:1,group_total:1,has_more:false,page:1};if(p.get('page')==='2')return {items:[image('page-two')],total:61,group_total:61,has_more:false,page:2};if(term)return {items:[image(`filter-${term}`)],total:1,group_total:1,has_more:false,page:1};return {items:[first,second],total:3,group_total:2,has_more:true,page:1}};
const context={
  document:{querySelector:get,documentElement:{dataset:{},style:{}},createElement:t=>new Element(t)},URLSearchParams,
  Option:function(label,value){return {label,value}},location:{search:'?scope=group%3AA',reload(){}},history:{replaceState(){}},
  window:{addEventListener:(n,f)=>{if(n==='keydown')keyEvents.push(f)},scrollTo(){}},
  localStorage:{getItem(){return null},setItem(){}},matchMedia(){return {matches:false}},
  navigator:{clipboard:{writeText:async()=>{}}},setTimeout,clearTimeout,
  fetch:async(url,options)=>{requests.push({url,options});let data;
    if(url==='/api/gallery/meta')data={token:'token',categories:[],scopes:[{value:'group:A',count:120},{value:'group:B',count:10}],users:[],sources:[]};
    else if(url.startsWith('/api/gallery/browse?'))data=browseResponse(url);
    else if(url.startsWith('/api/gallery/group?'))data={key:'batch-7',kind:'同批',count:2,members:[image('one'),image('member-two')]};
    else if(url.startsWith('/api/gallery/images/')){const id=decodeURIComponent(url.split('/').at(-1));data=id==='one'?new Promise(resolve=>pendingDetails.push(()=>resolve({prompt:'detail prompt one'}))):{prompt:'detail prompt '+id};}
    else if(url==='/api/export')data={status:'running'};
    else data={status:'done',summary:{dry_run:true,counts:{selected:120}}};
    return {ok:true,json:async()=>data};
  }
};
const page=fs.readFileSync(process.argv[2],'utf8');const scripts=[...page.matchAll(/<script>([\s\S]*?)<\/script>/g)];vm.runInNewContext(scripts.at(-1)[1],context);
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve))};
const key=(value)=>{const e={key:value,target:{tagName:'BODY'},preventDefault(){this.defaultPrevented=true}};for(const fn of keyEvents)fn(e);return e};
(async()=>{
 await settle();
 assert.ok(requests.some(r=>r.url.startsWith('/api/gallery/browse?')),'uses browse endpoint');
 assert.equal(requests.some(r=>r.url.startsWith('/api/gallery/images?')),false,'does not use old image pagination endpoint');
 assert.equal(get('#prev').onclick,undefined,'legacy pagination control is not wired');assert.equal(get('#next').onclick,undefined);
 const browse=requests.find(r=>r.url.startsWith('/api/gallery/browse?')).url;assert.match(browse,/scope=group%3AA/);assert.match(browse,/page=1/);assert.match(browse,/page_size=60/);
 const grid=get('#grid');assert.equal(grid.children.length,2);assert.match(get('#summary').textContent,/3/);
 assert.ok(grid.children.every(c=>/^span \d+$/.test(c.style.gridRowEnd)), 'reserve masonry rows before lazy images finish loading');
 assert.equal(get('#loadHint').hidden,false,'load sentinel is available');
 const firstCard=grid.children[0],preview=firstCard.querySelector('button.preview'),badge=firstCard.querySelector('button.batch-badge');
 assert.ok(preview,'image cover preview button exists');assert.ok(badge,'group badge exists');assert.equal(firstCard.querySelector('.info'),null);assert.equal(firstCard.textContent.includes('sample-tool'),false);

 badge.click();await settle();assert.equal(get('#groupViewer').open,true);assert.equal(get('#groupGrid').children.length,2);
 const groupUrl=requests.find(r=>r.url.startsWith('/api/gallery/group?')).url;assert.match(groupUrl,/scope=group%3AA/,'group membership honors submitted filters');
 assert.ok(get('#groupGrid').children.every(c=>!(c.querySelector('.info'))),'group member tiles contain no metadata panels');
 const memberButtons=get('#groupGrid').children.map(card=>card.classList.contains('preview')?card:card.querySelector('button.preview'));assert.ok(memberButtons.every(Boolean));
 memberButtons[0].click();await settle();assert.equal(get('#viewer').open,true);assert.equal(get('#viewerInfo').hidden,false,'group member viewer starts expanded');
 assert.ok(requests.some(r=>r.url.startsWith('/api/gallery/images/one')),'viewer fetches image detail lazily');
 get('#toggleInfo').click();assert.equal(get('#viewerInfo').hidden,true);assert.equal(get('#toggleInfo').getAttribute('aria-expanded'),'false');
 get('#viewerNext').click();await settle();assert.equal(get('#viewer').querySelector('img').src,'/image/member-two.jpg');assert.equal(get('#viewerInfo').hidden,true,'info collapse state persists while switching within group');
 pendingDetails.splice(0).forEach(resolve=>resolve());await settle();assert.ok(!get('#viewerDetails').textContent.includes('detail prompt one'),'late detail response for previous member cannot overwrite current member info');
 get('#viewerPrev').click();await settle();assert.equal(get('#viewer').querySelector('img').src,'/image/one.jpg');
 get('#viewer').onclick({target:get('#viewer')});assert.equal(get('#viewer').open,false);assert.equal(get('#groupViewer').open,true,'clicking the large viewer backdrop closes it and preserves group preview');
 memberButtons[0].click();await settle();get('#groupViewer').onclick({target:get('#groupViewer')});assert.equal(get('#groupViewer').open,false,'clicking the group backdrop closes the group preview');assert.equal(get('#viewer').open,false);

 // A fresh standalone opening expands metadata again, while I toggles and arrows preserve its state.
 preview.click();await settle();assert.equal(get('#viewerInfo').hidden,false);key('i');assert.equal(get('#viewerInfo').hidden,true);key('ArrowRight');await settle();assert.equal(get('#viewerInfo').hidden,true);key('i');assert.equal(get('#viewerInfo').hidden,false);key('Escape');assert.equal(get('#viewer').open,false);

 // Infinite loading appends page two while keeping the applied query.
 fields.keyword.value='';get('#next').onclick?.();
 get('#loadMore').click();await settle();const pageTwoUrl=requests.filter(r=>r.url.startsWith('/api/gallery/browse?')).at(-1).url;assert.match(pageTwoUrl,/page=2/);assert.match(pageTwoUrl,/scope=group%3AA/);assert.equal(grid.children.length,3);assert.ok(grid.children.every(c=>!c.textContent.includes('sample-tool')),'cards keep metadata out of visible text');
 // Export and later pages use submitted filters, never unsubmitted form edits.
 fields.scope.value='group:B';get('#export').onclick();await get('#exportForm').onsubmit({preventDefault(){}});assert.equal(JSON.parse(requests.find(r=>r.url==='/api/export').options.body).gallery_query.scope,'group:A');
 fields.keyword.value='slow';get('#filters').onsubmit({preventDefault(){}});await settle();fields.keyword.value='fast';get('#filters').onsubmit({preventDefault(){}});await settle();pendingSlow.splice(0).forEach(resolve=>resolve());await settle();assert.ok(grid.children.some(c=>c.querySelector('img')?.src==='/thumb/fast-result.jpg'));assert.equal(grid.children.some(c=>c.querySelector('img')?.src==='/thumb/slow-result.jpg'),false,'late old query cannot replace current results');
 get('#filterToggle').click();assert.equal(get('#advancedFilters').hidden,false);assert.equal(get('#filterToggle').getAttribute('aria-expanded'),'true');
 console.log('Browse groups, viewer navigation, filter state and incremental loading behave consistently.');
})().catch(e=>{console.error(e);process.exitCode=1});

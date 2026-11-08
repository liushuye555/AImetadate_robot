// Unit-test gallery query state and image/viewer presentation without a browser or network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag='div') {
    this.tagName = tag.toUpperCase(); this.value = ''; this.checked = false; this.options = [{value:''}];
    this.children = []; this.attributes = {}; this.listeners = {}; this.className = ''; this.hidden = false;
    this._textContent = ''; this.src = ''; this.href = ''; this.disabled = false;
    this.classList = {
      add: name => { if (!this.classList.contains(name)) this.className = `${this.className} ${name}`.trim(); },
      remove: name => { this.className = this.className.split(/\s+/).filter(x => x && x !== name).join(' '); },
      contains: name => this.className.split(/\s+/).includes(name),
    };
  }
  get textContent() { return this._textContent + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._textContent = String(value); this.children = []; }
  add(option) { this.options.push(option); }
  remove(index) { this.options.splice(index, 1); }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
  querySelector(selector) {
    const match = node => selector[0] === '.' ? node.classList.contains(selector.slice(1)) : node.tagName.toLowerCase() === selector.toLowerCase();
    const visit = node => { for (const child of node.children) { if (match(child)) return child; const found = visit(child); if (found) return found; } return null; };
    return visit(this) || null;
  }
  showModal() { this.open = true; }
  close() { this.open = false; for (const fn of this.listeners.close || []) fn(); }
  click() { if (this.onclick) this.onclick({preventDefault(){}}); for (const fn of this.listeners.click || []) fn({preventDefault(){}}); }
}
const elements = new Map();
const get = key => { if (!elements.has(key)) elements.set(key, new Element(key.startsWith('#') ? 'div' : key)); return elements.get(key); };
get('#viewer').append(new Element('img'));
const fields = {};
for (const name of ['keyword','category','scope','user','source','orientation','min_side','since','until','sort','dup_only']) fields[name] = new Element('input');
get('#filters').elements = fields;
get('#exportForm').elements = {out_dir: new Element('input'), no_captions: new Element('input'), dry_run: new Element('input')};
get('#exportForm').elements.dry_run.checked = true;
const sample = id => ({id,thumbnail:`/thumb/${id}.jpg`,url:`/image/${id}.jpg`,width:1024,height:768,category:'ai_metadata',ai_source:'sample-tool',seen_at:'2026-11-08T12:00:00',scope:'group:A',user_id:'user-42',text_excerpt:`sample prompt ${id}`});
const requests = [];
const context = {
  document: {querySelector:get, documentElement:{dataset:{}}, createElement:tag=>new Element(tag)},
  URLSearchParams, Option:function(label,value){return {label,value};},
  location:{search:'?scope=group%3AA',reload(){}}, history:{replaceState(){}},
  window:{addEventListener(){}, scrollTo(){}},
  localStorage:{getItem(){return null;},setItem(){}}, matchMedia(){return {matches:false}},
  setTimeout, clearTimeout,
  fetch:async (url,options)=>{
    requests.push({url,options});
    let data;
    if (url === '/api/gallery/meta') data = {token:'token',categories:[],scopes:[{value:'group:A',count:120},{value:'group:B',count:10}],users:[],sources:[]};
    else if (url.startsWith('/api/gallery/images')) data = {total:120,items:[sample('one'),sample('two')],has_more:true};
    else if (url === '/api/export') data = {status:'running'};
    else data = {status:'done',summary:{dry_run:true,counts:{selected:120}}};
    return {ok:true,json:async()=>data};
  }
};
const page = fs.readFileSync(process.argv[2],'utf8');
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)];
vm.runInNewContext(scripts.at(-1)[1],context);
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
(async()=>{
  await settle();
  assert.match(get('#summary').textContent,/找到/);
  assert.match(requests.find(r=>r.url.startsWith('/api/gallery/images')).url,/scope=group%3AA/);

  // The grid exposes only the preview control; descriptive fields belong in the viewer.
  const grid = get('#grid');
  assert.equal(grid.children.length,2);
  for (const card of grid.children) {
    assert.equal(card.children.length,1);
    assert.equal(card.children[0].tagName,'BUTTON');
    assert.equal(card.children[0].classList.contains('preview'),true);
    assert.equal(card.querySelector('.info'),null);
  }
  const viewer = get('#viewer'), viewerInfo = get('#viewerInfo'), toggleInfo = get('#toggleInfo');
  grid.children[0].children[0].click();
  assert.equal(viewer.open,true);
  assert.equal(viewerInfo.hidden,true);
  assert.equal(toggleInfo.getAttribute('aria-expanded'),'false');
  for (const metadata of ['ai_metadata','sample-tool','2026-11-08','group:A','user-42','sample prompt one']) {
    assert.ok(viewerInfo.textContent.includes(metadata),`viewer info should contain ${metadata}`);
  }
  assert.equal(grid.querySelector('.info'),null);
  toggleInfo.click();
  assert.equal(viewerInfo.hidden,false);
  assert.equal(toggleInfo.getAttribute('aria-expanded'),'true');
  toggleInfo.click();
  assert.equal(viewerInfo.hidden,true);
  assert.equal(toggleInfo.getAttribute('aria-expanded'),'false');
  grid.children[1].children[0].click();
  assert.equal(viewerInfo.hidden,true,'opening a different image starts with metadata collapsed');
  assert.equal(toggleInfo.getAttribute('aria-expanded'),'false');

  fields.scope.value='group:B'; // Edited, but not searched.
  get('#export').onclick();
  await get('#exportForm').onsubmit({preventDefault(){}});
  assert.equal(JSON.parse(requests.find(r=>r.url==='/api/export').options.body).gallery_query.scope,'group:A');
  get('#next').onclick(); await settle();
  let last=requests.filter(r=>r.url.startsWith('/api/gallery/images')).at(-1).url;
  assert.match(last,/scope=group%3AA/); assert.match(last,/page=2/);
  get('#filters').onsubmit({preventDefault(){}}); await settle();
  last=requests.filter(r=>r.url.startsWith('/api/gallery/images')).at(-1).url;
  assert.match(last,/scope=group%3AB/); assert.match(last,/page=1/);
  console.log('Image-only grid, collapsed viewer metadata, and applied filters behave consistently.');
})().catch(e=>{console.error(e);process.exitCode=1;});

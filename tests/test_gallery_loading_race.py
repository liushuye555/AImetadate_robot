"""Execute the generated gallery loader to reproduce in-flight filter changes."""
import json
import shutil
import subprocess

import pytest

from qq_onebot_whitelist.build_image_view import _gallery_page


def function_source(page, name):
    start = page.index('function ' + name + '(')
    if page[start-6:start] == 'async ':
        start -= 6
    opening = page.index('{', start)
    depth = 1
    closing = opening + 1
    while depth:
        if page[closing] == '{':
            depth += 1
        elif page[closing] == '}':
            depth -= 1
        closing += 1
    return page[start:closing]


@pytest.mark.parametrize('initial_chunk', [0, 1])
def test_filter_change_restarts_at_first_chunk_and_ignores_old_callback(initial_chunk):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed to execute the generated gallery loader')
    page = _gallery_page(title='全部', count=360, chunk_count=3)
    accept_start = page.index('window.__galleryAcceptChunk=')
    accept_end = page.index('function loadChunk(', accept_start)
    code = '\n'.join([
        function_source(page, 'resetGrid'), page[accept_start:accept_end],
        function_source(page, 'loadChunk'), function_source(page, 'loadNext'),
    ])
    harness = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const scripts=[];
const document={currentScript:null,head:{appendChild(script){scripts.push(script);}},
  createElement(){return {dataset:{}};}};
const context={document,window:{},console};
vm.createContext(context);
const prefix=`
  const cells=[],itemData=[],itemCards=[],groups=new Map(),chunkPromises=new Map();
  let nextChunk=0,loading=false,activeRequest=null,currentIndex=-1,errorMessage='';
  let viewGeneration=0,requestSerial=0,groupNav=null,groupToken=0;
  let chunkBase='';const buildToken='?v=test',chunkCount=3;
  const overlay={style:{}},grid={textContent:''};
  function updateProgress(){} function closeGroupLayer(){} function hintDefault(){}
  function syncInfoVisibility(){}
  function renderItems(items){for(const item of items){cells.push(item);itemData.push(item);}}
`;
vm.runInContext(prefix+input.code+`
globalThis.hooks={loadNext,resetGrid,setNext(i){nextChunk=i;},
  stats(){return {loading,nextChunk,items:itemData.map(x=>x.id),settled:activeRequest?.settled};}};
`,context);
(async()=>{
  context.hooks.setNext(input.initial_chunk);
  const oldLoad=context.hooks.loadNext();
  assert.equal(scripts.length,1);
  context.hooks.resetGrid();
  assert.equal(scripts.length,2,'filter change must start a fresh first-chunk request');
  assert.ok(scripts[1].src.includes('chunk-0001.js'),'fresh filtered load begins at chunk 1');
  await oldLoad;
  assert.equal(context.hooks.stats().loading,true,'old completion must not clear new loading state');
  document.currentScript=scripts[0];
  context.window.__galleryAcceptChunk(input.initial_chunk,[{id:'stale-result'}]);
  assert.equal(context.hooks.stats().settled,false,'late old callback must not resolve new request');
  document.currentScript=scripts[1];
  context.window.__galleryAcceptChunk(0,[{id:'candidate'}]);
  await new Promise(resolve=>setImmediate(resolve));
  const result=context.hooks.stats();
  assert.equal(result.loading,false);
  assert.equal(result.nextChunk,1,'middle-chunk callback must not skip beginning of new results');
  assert.deepEqual(Array.from(result.items),['candidate']);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness], input=json.dumps({'code': code, 'initial_chunk': initial_chunk}),
                            text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

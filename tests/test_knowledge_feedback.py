import json

import pytest
import yaml

from qq_onebot_whitelist.knowledge_feedback import submit_feedback, propose, apply_proposal, compare_history, proposals
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist.store import Store

MODEL = LLMConfig('https://example.invalid/v1','test-key','test')


def setup(tmp_path):
    data=tmp_path/'data'; data.mkdir()
    path=tmp_path/'config.yaml'
    profile={'enabled':True,'topics':['ai_drawing'],'description':'old','extraction':{'enabled':True},'history':{'enabled':True},'feedback':{'enabled':True,'optimization_enabled':True},'max_tokens_per_day':200000}
    path.write_text(yaml.safe_dump({'storage':{'data_dir':str(data)},'knowledge':{'enabled':True,'groups':{'group:123':profile}}}),encoding='utf-8')
    store=Store(data/'bot.db')
    store.record_message(scope='group:123',user_id='10',text='解决方案成功',raw={'message_id':1,'time':1780000000})
    store.record_message(scope='group:999',user_id='10',text='别群消息',raw={'message_id':2,'time':1780000000})
    return path,data


def proposal_response(messages,model):
    return {'topics':['AI绘图工作流'],'description':'依据节点与版本分析，不确定内容标为候选','reason':'依据人工纠错'},50


def test_disabled_never_creates_database(tmp_path):
    path=tmp_path/'config.yaml'; path.write_text('{}',encoding='utf-8')
    for fn,args in [(submit_feedback,('123','confirmed')),(propose,('123',)),(apply_proposal,('123',1)),(compare_history,('123',1))]:
        assert fn(path,*args)['status']=='disabled'
    assert not (tmp_path/'data').exists()


def test_feedback_cannot_cross_group_and_redacts(tmp_path):
    path,data=setup(tmp_path)
    with pytest.raises(ValueError):submit_feedback(path,'123','confirmed',message_id=2)
    assert submit_feedback(path,'123','missed','api_key=sk-abcdefghijklmnopqrstuvwxyz123456',message_id=1)['status']=='completed'
    db=KnowledgeDB(data/'knowledge.db')
    with db.conn() as conn:
        assert 'sk-abcdefghijklmnopqrstuvwxyz123456' not in conn.execute('SELECT notes FROM feedback').fetchone()[0]


def test_proposal_apply_only_changes_allowed_fields_and_versions(tmp_path):
    path,data=setup(tmp_path)
    submit_feedback(path,'123','missed',message_id=1)
    before=yaml.safe_load(path.read_text(encoding='utf-8'))
    result=propose(path,'123',request=proposal_response,model=MODEL)
    assert result['status']=='completed'
    assert yaml.safe_load(path.read_text(encoding='utf-8'))==before
    assert propose(path,'123',request=lambda *a:pytest.fail('cached'),model=MODEL)['cached']
    assert apply_proposal(path,'123',result['proposal_id'])['revision']==2
    after=yaml.safe_load(path.read_text(encoding='utf-8'))['knowledge']['groups']['group:123']
    assert after['feedback']==before['knowledge']['groups']['group:123']['feedback']
    assert after['history']==before['knowledge']['groups']['group:123']['history']
    assert after['topics']==['AI绘图工作流']
    assert apply_proposal(path,'999',result['proposal_id'])['status']=='disabled'


def test_rejects_permission_proposal_and_default_inheritance(tmp_path):
    path,data=setup(tmp_path);submit_feedback(path,'123','confirmed',message_id=1)
    with pytest.raises(RuntimeError):propose(path,'123',request=lambda *a:({'topics':[],'description':'x','reason':'y','enabled':True},10),model=MODEL)
    raw=yaml.safe_load(path.read_text());raw['knowledge']['defaults']={'feedback':{'optimization_enabled':True}}
    del raw['knowledge']['groups']['group:123']['feedback']['optimization_enabled'];path.write_text(yaml.safe_dump(raw),encoding='utf-8')
    assert propose(path,'123',request=lambda *a:pytest.fail('off'))['status']=='disabled'


def test_compare_uses_identical_evidence_and_does_not_change_live_items(tmp_path):
    path,data=setup(tmp_path);submit_feedback(path,'123','missed',message_id=1)
    pid=propose(path,'123',request=proposal_response,model=MODEL)['proposal_id']
    seen=[]
    def request(messages,model):
        task=json.loads(messages[1]['content']);seen.append(task['messages'])
        return {'items':[{'title':'排错','summary':'成功','kind':'排错','topic':'绘图','value':'high','evidence_state':'verified','evidence_ids':[1],'file_ids':[]}]},20
    result=compare_history(path,'123',pid,request=request,model=MODEL)
    assert seen[0]==seen[1]
    assert result['before']['confirmed_message_hits']==result['after']['confirmed_message_hits']==1
    assert KnowledgeDB(data/'knowledge.db').items()==[]
    assert compare_history(path,'123',pid,request=lambda *a:pytest.fail('cached'),model=MODEL)['status']=='completed'
    assert proposals(path,'123')['proposals'][0]['comparison_json']


def test_apply_rejects_stale_config_and_compare_invalid_evidence(tmp_path):
    path,data=setup(tmp_path);submit_feedback(path,'123','missed',message_id=1)
    pid=propose(path,'123',request=proposal_response,model=MODEL)['proposal_id']
    with pytest.raises(RuntimeError):compare_history(path,'123',pid,request=lambda *a:({'items':[{'title':'x','summary':'x','value':'high','evidence_ids':[2]}]},10),model=MODEL)
    raw=yaml.safe_load(path.read_text());raw['knowledge']['groups']['group:123']['description']='changed';path.write_text(yaml.safe_dump(raw),encoding='utf-8')
    with pytest.raises(ValueError):apply_proposal(path,'123',pid)


def test_http_feedback_requires_dedicated_token_and_live_opt_in(tmp_path):
    import threading
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from qq_onebot_whitelist.view_server import make_server
    from qq_onebot_whitelist.knowledge_feedback import feedback_token
    path,data=setup(tmp_path)
    token=feedback_token(data)
    server=make_server(tmp_path,0)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def post(payload):
        req=Request(f'http://127.0.0.1:{server.server_address[1]}/api/knowledge/feedback',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req) as response:return json.loads(response.read())
    try:
        with pytest.raises(HTTPError) as err:post({'token':'bad','scope':'group:123','kind':'missed','message_id':1})
        assert err.value.code==403
        assert post({'token':token,'scope':'group:123','kind':'missed','message_id':1})['status']=='completed'
        with pytest.raises(HTTPError) as err:post({'token':token,'scope':'group:123','kind':'missed','message_id':2})
        assert err.value.code==400
        raw=yaml.safe_load(path.read_text());raw['knowledge']['enabled']=False;path.write_text(yaml.safe_dump(raw),encoding='utf-8')
        assert post({'token':token,'scope':'group:123','kind':'missed','message_id':1})['status']=='disabled'
    finally:
        server.shutdown();server.server_close()


def test_report_feedback_controls_escape_and_internal_runs_are_hidden(tmp_path):
    from qq_onebot_whitelist.knowledge import write_view
    from qq_onebot_whitelist.knowledge_feedback import feedback_controls
    path,data=setup(tmp_path);submit_feedback(path,'123','missed',message_id=1)
    propose(path,'123',request=proposal_response,model=MODEL)
    db=KnowledgeDB(data/'knowledge.db')
    db.claim('internal','group:123','model:primary:batch',10,100000,1,1)
    db.finish('internal','group:123',{'summary':[{'text':'must-not-show','evidence_ids':[1]}]},10,extraction=False,glossary=False)
    html=write_view(data).read_text(encoding='utf-8')
    assert 'must-not-show' not in html
    assert 'missed-submit' in html and '/api/knowledge/feedback' in html
    assert '" onclick=' not in feedback_controls('group:123','" onclick="bad')


def test_original_file_busid_preserved_for_refresh_and_retry(tmp_path):
    from qq_onebot_whitelist.resources import extract_file_segments
    source=extract_file_segments({'message':[{'type':'file','data':{'id':'f','name':'x.json','busid':102,'size':50}}]})[0]
    assert source['busid']==102
    source.update(scope='group:123',message_id=1)
    db=KnowledgeDB(tmp_path/'derived.db');db.asset(source,{'status':'failed'})
    assert json.loads(db.pending_assets('group:123')[0]['source_json'])['busid']==102

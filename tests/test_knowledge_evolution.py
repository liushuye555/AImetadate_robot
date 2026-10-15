import json
from datetime import datetime

import yaml

from qq_onebot_whitelist.knowledge import analyze
from qq_onebot_whitelist.knowledge_store import KnowledgeDB, read_records
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist.store import Store


MODEL = LLMConfig('https://model.invalid/v1', 'test-key', 'model')


def setup(tmp_path, *, track=False, infer=False, defaults=None):
    data = tmp_path / 'data'
    store = Store(data / 'bot.db')
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(data)}, 'knowledge': {
        'enabled': True, 'defaults': defaults or {}, 'groups': {'group:123': {'enabled': True,
        'extraction': {'enabled': True, 'track_topics': track},
        'glossary': {'enabled': True, 'infer_context': infer}}}}}), encoding='utf-8')
    return path, store, KnowledgeDB(data / 'knowledge.db')


def record(store, mid, text):
    store.record_message(scope='group:123', user_id='local-private-id', text=text, raw={
        'message_id': mid, 'time': int(datetime.fromisoformat(f'2026-10-15T12:0{mid}:00+08:00').timestamp())})


def item(mid, **fields):
    return dict(title='节点报错', summary='本段提供排错线索', kind='排错', topic='工作流',
                value='candidate', evidence_ids=[mid], file_ids=[], **fields)


def test_live_followup_updates_topic_without_losing_question_or_sources(tmp_path):
    path, store, db = setup(tmp_path, track=True)
    record(store, 1, '节点报错，还没有解决')
    first = {'items': [item(1, category='question', status='open', evidence_state='unresolved',
                            known='节点报错', missing='缺少版本和报错详情')]}
    analyze(path, '123', feature='extraction', kind='live', request=lambda *a: (first, 20), model=MODEL)
    topic = db.thread_candidates('group:123')[0]
    record(store, 2, '更新节点以后已经验证恢复了')
    captured = []
    def followup(messages, model):
        task = json.loads(messages[1]['content']); captured.append(task)
        return {'items': [item(2, category='knowledge', status='resolved', evidence_state='verified',
            thread_id=task['threads'][0]['id'], link_reason='对同一节点报错补充验证结果',
            known='更新节点以后恢复', missing='具体版本仍未提供',
            resolution_evidence=[{'message_id': 2, 'quote': '更新节点以后已经验证恢复了'}])]}, 20
    result = analyze(path, '123', feature='extraction', kind='live', records=read_records(store.path, 'group:123', after_id=1),
                     request=followup, model=MODEL)
    assert result['status'] == 'completed'
    threads = db.threads('group:123')
    assert len(threads) == 1 and threads[0]['id'] == topic['id']
    assert threads[0]['status'] == 'resolved' and len(threads[0]['events']) == 2
    assert threads[0]['evidence_ids'] == [1, 2]
    assert len(db.items('group:123')) == 2
    page = (store.path.parent / 'view/knowledge.html').read_text(encoding='utf-8')
    assert page.count('<article ') == 1 and '话题记录 2 次' in page
    assert '还没有解决' in page and '已经验证恢复了' in page


def test_new_capabilities_stay_off_and_do_not_inherit_defaults(tmp_path, monkeypatch):
    path, store, db = setup(tmp_path, defaults={'extraction': {'track_topics': True}, 'glossary': {'infer_context': True}})
    record(store, 1, '没有答案')
    monkeypatch.setattr(KnowledgeDB, 'thread_candidates', lambda *a, **k: (_ for _ in ()).throw(AssertionError('off')))
    captured = []
    def request(messages, model):
        captured.append(json.loads(messages[1]['content']))
        return {'items': [item(1, thread_id='foreign', status='resolved', evidence_state='unresolved')]}, 20
    result = analyze(path, '123', feature='extraction', kind='batch', request=request, model=MODEL)
    assert captured[0]['capabilities'] == {'track_topics': False, 'infer_context': False}
    assert result['status'] == 'completed' and db.threads('group:123') == []
    assert 'thread_id' not in result['items'][0]


def test_context_inference_is_candidate_even_if_model_supplies_definition_support(tmp_path):
    path, store, db = setup(tmp_path, infer=True)
    record(store, 1, '跑图时打开工作流')
    record(store, 2, '跑图后得到图片')
    output = {'terms': [{'term': '跑图', 'meaning': '本群指生成图片', 'evidence_ids': [1, 2],
        'inference_kind': 'inferred', 'inference_note': '两条用例分别出现工作流和图片结果',
        'inference_evidence': [{'message_id': 1, 'quote': '跑图时打开工作流'},
                               {'message_id': 2, 'quote': '跑图后得到图片'}]}]}
    analyze(path, '123', feature='glossary', kind='manual:glossary', request=lambda *a: (output, 20), model=MODEL)
    term = db.terms('group:123')[0]
    assert term['inference_kind'] == 'inferred' and term['status'] == 'candidate'
    assert len(term['inference_evidence']) == 2
    assert '上下文推断' in (store.path.parent / 'view/glossary.html').read_text(encoding='utf-8')

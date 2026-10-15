import json
import sys

import yaml

from qq_onebot_whitelist import knowledge
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist.store import Store


MODEL = LLMConfig('https://model.invalid/v1', 'test-key', 'test-model')


def setup(tmp_path, features):
    data = tmp_path / 'data'
    store = Store(data / 'bot.db')
    store.record_message(scope='group:123', user_id='private-user', text='跑图指生成图片，调整节点后恢复', raw={})
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(data)}, 'knowledge': {
        'enabled': True, 'groups': {'group:123': {'enabled': True,
            **{feature: {'enabled': True} for feature in features}}}}}), encoding='utf-8')
    return path, data


def output():
    return {'items': [{'title': '节点调整', 'summary': '调整后恢复', 'kind': '排错',
        'topic': '绘图', 'value': 'candidate', 'evidence_ids': [1]}],
        'terms': [{'term': '跑图', 'meaning': '生成图片', 'evidence_ids': [1]}]}


def test_closed_glossary_is_not_sent_as_model_context(tmp_path):
    path, data = setup(tmp_path, ['extraction'])
    db = KnowledgeDB(data / 'knowledge.db')
    db.set_term('group:123', '隐藏词表', '禁止带入本次任务')
    captured = []
    def request(messages, model):
        captured.append(json.loads(messages[1]['content']))
        return output(), 20
    knowledge.analyze(path, '123', feature='extraction', kind='batch', request=request, model=MODEL)
    assert captured[0]['glossary'] == []
    assert captured[0]['requested'] == ['extraction']
    assert '禁止带入本次任务' not in json.dumps(captured, ensure_ascii=False)
    assert len(db.terms('group:123')) == 1
    assert len(db.items('group:123')) == 1


def test_explicit_terminology_items_do_not_enter_knowledge(tmp_path):
    path, data = setup(tmp_path, ['extraction', 'glossary'])
    result = output()
    result['items'][0]['content_type'] = 'term'
    result = knowledge.analyze(path, '123', feature='extraction', kind='batch',
                               request=lambda *a: (result, 20), model=MODEL)
    db = KnowledgeDB(data / 'knowledge.db')
    assert result['items'] == [] and db.items('group:123') == []
    assert db.terms('group:123')[0]['term'] == '跑图'


def test_manual_glossary_does_not_extract_knowledge_and_search_is_separate(tmp_path):
    path, data = setup(tmp_path, ['extraction', 'glossary'])
    knowledge.analyze(path, '123', feature='glossary', kind='manual:glossary',
                      request=lambda *a: (output(), 20), model=MODEL)
    db = KnowledgeDB(data / 'knowledge.db')
    assert db.items('group:123') == []
    db.set_term('group:999', '跑图', '别群释义')
    event = {'message_type': 'group', 'group_id': 123}
    reply = knowledge.command_reply('群术语 跑图', event, path)
    assert '生成图片' in reply and '候选解释' in reply and '别群释义' not in reply
    assert knowledge.command_reply('群知识 跑图', event, path) == '本群暂无匹配知识。'


def test_disabled_term_query_does_not_create_knowledge_database(tmp_path, monkeypatch, capsys):
    path, data = setup(tmp_path, ['extraction'])
    assert '尚未开启' in knowledge.command_reply('群术语', {'message_type': 'group', 'group_id': 123}, path)
    monkeypatch.setattr(sys, 'argv', ['knowledge', '--config', str(path), 'terms', '--group', '123'])
    knowledge.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'disabled'
    assert not (data / 'knowledge.db').exists()


def test_term_search_filters_before_limit_and_keeps_group_boundary(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    for number in range(70):
        db.set_term('group:123', f'a{number:03}', '普通释义')
    db.set_term('group:123', 'z目标', '准确匹配')
    db.set_term('group:999', 'z目标', '别群内容')
    rows = db.terms('group:123', keyword='准确', limit=1)
    assert len(rows) == 1 and rows[0]['term'] == 'z目标'


def test_cli_feature_selection_uses_independent_manual_task(tmp_path, monkeypatch, capsys):
    path, data = setup(tmp_path, ['extraction', 'glossary'])
    captured = []
    def analyze(*args, **kwargs):
        captured.append(kwargs)
        return {'status': 'completed'}
    monkeypatch.setattr(knowledge, 'analyze', analyze)
    monkeypatch.setattr(sys, 'argv', ['knowledge', '--config', str(path), 'analyze', '--group', '123', '--feature', 'glossary'])
    knowledge.main()
    assert captured[0]['feature'] == 'glossary' and captured[0]['kind'] == 'manual:glossary'

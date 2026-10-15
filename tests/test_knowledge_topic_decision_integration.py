import json

import pytest
import yaml

from qq_onebot_whitelist import knowledge
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig


MODEL = LLMConfig('https://model.invalid/v1', 'test-only', 'model')
SCOPE = 'group:123'


def setup(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(tmp_path / 'data')},
        'knowledge': {'enabled': True, 'groups': {SCOPE: {'enabled': True,
            'extraction': {'enabled': True, 'track_topics': True}, 'max_tokens_per_day': 500000}}}}), encoding='utf-8')
    db = KnowledgeDB(tmp_path / 'data/knowledge.db')
    return path, db


def record(mid):
    return dict(id=mid, scope=SCOPE, text='Same service is back' if mid == 2 else 'Service outage',
                time=f'2026-10-15T12:0{mid}:00+08:00', quoted_id=None, quoted_text='',
                files=[], links=[], segments=['text'])


def output(mid):
    return {'items': [dict(title='Public service outage', summary='Actual followup', kind='排错',
        topic='service', value='candidate', category='transient', evidence_state='reported',
        evidence_ids=[mid], file_ids=[])]}


def test_incomplete_new_action_keeps_content_for_focused_adjudication(tmp_path):
    path, db = setup(tmp_path)
    def request(messages, cfg):
        task = json.loads(messages[1]['content'])
        if task.get('task_type') == 'topic_decisions':
            return {'decisions': [dict(index=0, action='existing', thread_id=task['threads'][0]['id'],
                reason='Same public service and a new recovery report', status='in_progress')]}, 7
        result = output(max(row['id'] for row in task['messages']))
        result['items'][0]['topic_action'] = 'new'
        return result, 13
    knowledge.analyze(path, SCOPE, feature='extraction', records=[record(1)], request=request, model=MODEL)
    result = knowledge.analyze(path, SCOPE, feature='extraction', records=[record(2)], request=request, model=MODEL)
    assert len(result['items']) == 1 and len(db.items(SCOPE)) == 2
    assert len(db.threads(SCOPE)) == 1 and len(db.threads(SCOPE)[0]['events']) == 2


def test_real_model_omission_gets_an_explicit_decision_and_idempotent_cache(tmp_path):
    path, db = setup(tmp_path)
    calls = []
    def request(messages, cfg):
        task = json.loads(messages[1]['content']); calls.append(task)
        if task.get('task_type') == 'topic_decisions':
            return {'decisions': [dict(index=0, action='existing', thread_id=task['threads'][0]['id'],
                reason='Same public service outage, current report adds recovery information', status='in_progress')]}, 7
        mid = max(r['id'] for r in task['messages'] if not r.get('context_only'))
        return output(mid), 13
    knowledge.analyze(path, SCOPE, feature='extraction', records=[record(1)], request=request, model=MODEL)
    kwargs = dict(feature='extraction', records=[record(2)], request=request, model=MODEL)
    result = knowledge.analyze(path, SCOPE, **kwargs)
    assert len(db.threads(SCOPE)) == 1, 'omitted thread_id must not silently create another topic'
    assert len(db.threads(SCOPE)[0]['events']) == 2
    assert result['tokens'] == 20
    assert len(calls) == 3
    with db.conn() as conn:
        assert conn.execute('select sum(tokens) from runs').fetchone()[0] == 33
    assert knowledge.analyze(path, SCOPE, **kwargs)['cached'] is True
    assert len(calls) == 3


def test_invalid_decision_does_not_publish_a_duplicate_topic(tmp_path):
    path, db = setup(tmp_path)
    knowledge.analyze(path, SCOPE, feature='extraction', records=[record(1)],
        request=lambda *_: (output(1), 13), model=MODEL)
    def request(messages, cfg):
        if json.loads(messages[1]['content']).get('task_type') == 'topic_decisions':
            return {'decisions': []}, 7
        return output(2), 13
    with pytest.raises(RuntimeError, match='话题决策不完整'):
        knowledge.analyze(path, SCOPE, feature='extraction', records=[record(2)], request=request, model=MODEL)
    assert len(db.items(SCOPE)) == 1 and len(db.threads(SCOPE)) == 1


def test_known_primary_usage_is_settled_before_decision_budget_claim(tmp_path):
    path, db = setup(tmp_path)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['knowledge']['groups'][SCOPE]['max_tokens_per_day'] = 26000
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    def request(messages, cfg):
        task = json.loads(messages[1]['content'])
        if task.get('task_type') == 'topic_decisions':
            with db.conn() as conn:
                pending_primary = conn.execute("select tokens from runs where kind like 'model:primary:%'").fetchone()
            assert pending_primary[0] == 13
            return {'decisions': [dict(index=0, action='existing', thread_id=task['threads'][0]['id'],
                reason='Same public service, new recovery report', status='in_progress')]}, 7
        return output(max(row['id'] for row in task['messages'])), 13
    knowledge.analyze(path, SCOPE, feature='extraction', records=[record(1)], request=request, model=MODEL)
    result = knowledge.analyze(path, SCOPE, feature='extraction', records=[record(2)], request=request, model=MODEL)
    assert result['status'] == 'completed'
    with db.conn() as conn:
        assert conn.execute('select sum(tokens) from runs').fetchone()[0] == 33


def test_topic_failure_retry_reuses_the_validated_primary_output(tmp_path):
    path, db = setup(tmp_path)
    primary_calls = []
    decision_calls = []
    def request(messages, cfg):
        task = json.loads(messages[1]['content'])
        if task.get('task_type') == 'topic_decisions':
            decision_calls.append(1)
            if len(decision_calls) == 1:
                raise TimeoutError('simulated topic model outage')
            return {'decisions': [dict(index=0, action='existing', thread_id=task['threads'][0]['id'],
                reason='Same service outage with a recovery report', status='in_progress')]}, 7
        primary_calls.append(1)
        return output(max(row['id'] for row in task['messages'])), 13
    knowledge.analyze(path, SCOPE, feature='extraction', records=[record(1)], request=request, model=MODEL)
    kwargs = dict(feature='extraction', records=[record(2)], request=request, model=MODEL)
    with pytest.raises(RuntimeError):
        knowledge.analyze(path, SCOPE, **kwargs)
    assert knowledge.analyze(path, SCOPE, **kwargs)['status'] == 'completed'
    assert len(primary_calls) == 2 and len(decision_calls) == 2
    assert len(db.threads(SCOPE)) == 1


def test_topic_retry_keeps_grounded_file_preview_without_redownloading(tmp_path, monkeypatch):
    path, db = setup(tmp_path)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['knowledge']['groups'][SCOPE]['files'] = {'enabled': True, 'preview_enabled': True}
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    from qq_onebot_whitelist import knowledge_file_material
    preview_calls = []
    def prepare(config_path, scope, rows):
        prepared = []
        for row in rows:
            if row['files']:
                preview_calls.append(row['id'])
            prepared.append({**row, 'files': [{**f, 'preview': {'status': 'ok',
                'text': 'Python 3.12. Run python -m app. Works correctly.'}} for f in row['files']]})
        return prepared
    monkeypatch.setattr(knowledge_file_material, 'prepare_file_previews', prepare)
    retained_values = []
    monkeypatch.setattr(knowledge, 'retain_selected_files', lambda config, db, records, result:
        retained_values.extend(item['value'] for item in result['items'] if item['file_ids']))
    topic_calls = []
    def request(messages, cfg):
        task = json.loads(messages[1]['content'])
        if task.get('task_type') == 'topic_decisions':
            topic_calls.append(1)
            if len(topic_calls) == 1:
                raise TimeoutError('temporary decision outage')
            return {'decisions': [dict(index=0, action='existing', thread_id=task['threads'][0]['id'],
                reason='A tutorial for the same service issue', status='in_progress')]}, 7
        mid = max(row['id'] for row in task['messages'])
        result = output(mid)
        if mid == 2:
            result['items'][0].update(value='high', category='knowledge', file_ids=['file1'],
                quality={'basis': 'reproducible_method', 'conditions': ['Python 3.12'],
                    'actions': ['Run python -m app'], 'result_quote': {'message_id': 2, 'quote': 'Works correctly.'}})
        return result, 13
    knowledge.analyze(path, SCOPE, feature='extraction', kind='batch', records=[record(1)], request=request, model=MODEL)
    source = {**record(2), 'files': [{'file_id': 'file1', 'file_name': 'tutorial.txt', 'file_size': 60}]}
    kwargs = dict(feature='extraction', kind='batch', records=[source], request=request, model=MODEL)
    with pytest.raises(RuntimeError):
        knowledge.analyze(path, SCOPE, **kwargs)
    result = knowledge.analyze(path, SCOPE, **kwargs)
    assert result['items'][0]['value'] == 'high'
    assert result['items'][0]['quality']['result_quote']['quote'] == 'Works correctly.'
    assert preview_calls == [2] and retained_values == ['high']

"""Integration regressions found during the knowledge evolution review."""
import json
import re

import pytest
import yaml

from qq_onebot_whitelist import knowledge
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig


SCOPE = 'group:123'
PRIMARY = LLMConfig('https://primary.invalid/v1', 'local-test-key', 'primary')
REVIEW = LLMConfig('https://review.invalid/v1', 'local-test-key', 'review')


def record(mid, *, day=15, text='Actual progress', links=None):
    return dict(id=mid, scope=SCOPE, text=text, time=f'2026-10-{day:02}T12:00:00+08:00',
                quoted_id=None, quoted_text='', links=links or [], segments=['text'], files=[])


def item(mid, **changes):
    value = dict(title=f'Issue {mid}', summary='Actual progress', kind='debug', topic='node',
                 value='candidate', evidence_ids=[mid], file_ids=[], evidence_state='reported',
                 category='question')
    value.update(changes)
    return value


def configured(tmp_path, *, review=False, infer=False):
    data = tmp_path / 'data'
    settings = dict(enabled=True, extraction={'enabled': True, 'track_topics': True},
                    glossary={'enabled': True, 'infer_context': infer},
                    models={'review_enabled': review}, max_tokens_per_day=1000000)
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(data)}, 'knowledge': {
        'enabled': True, 'groups': {SCOPE: settings}}}), encoding='utf-8')
    return path, KnowledgeDB(data / 'knowledge.db')


@pytest.mark.parametrize('category,value', [('transient', 'candidate'), ('resource', 'candidate'),
                                            ('knowledge', 'high')])
def test_topic_metadata_survives_the_global_items_display_window(tmp_path, category, value):
    path, db = configured(tmp_path)
    url = 'https://example.invalid/original-resource'
    original = item(1, category=category, value=value,
                    resource={'name': 'Original tool', 'url': url, 'purpose': 'Debugging'})
    sources = [record(1, links=[url])]
    if value == 'high':
        sources[0]['text'] = 'On v1 update the node: recovered'
        original['quality'] = {'basis': 'reproducible_method', 'conditions': ['v1'],
            'actions': ['update the node'], 'result_quote': {'message_id': 1, 'quote': 'recovered'}}
    validated = knowledge.validate_result({'items': [original]}, sources, track_topics=True)
    db.finish('seed', SCOPE, validated, 1, extraction=True, glossary=False,
              track_topics=True, records=sources)
    original_key = db.items(SCOPE)[0]['key']
    # Later untracked items evict the original from write_view's 500-item window.
    for batch in range(9):
        db.finish(f'fill-{batch}', SCOPE, {'items': [item(10 + batch * 60 + i)
                  for i in range(60)]}, 1, extraction=True, glossary=False)
    assert original_key not in {row['key'] for row in db.items(limit=500)}
    knowledge.write_view(db.path.parent)
    page = (db.path.parent / 'view/knowledge.html').read_text(encoding='utf-8')
    card = re.search(r'(<article[^>]*><h2>Issue 1</h2>.*?</article>)', page, re.S).group(1)
    assert f'data-category="{category}"' in card
    assert f'data-value="{value}"' in card
    assert db.threads(SCOPE)[0]['category'] == category
    if category == 'resource':
        assert f'href="{url}"' in card


def test_review_retry_uses_the_candidate_snapshot_shown_in_its_cached_task(tmp_path, monkeypatch):
    path, db = configured(tmp_path, review=True)
    db.finish('seed', SCOPE, {'items': [item(1)]}, 1, extraction=True, glossary=False,
              track_topics=True, records=[record(1, day=1)])
    old_id = db.thread_candidates(SCOPE)[0]['id']
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *_: REVIEW)
    monkeypatch.setattr(knowledge, 'write_view', lambda *_: None)
    calls = []

    def request(messages, model):
        task = json.loads(messages[1]['content'])
        calls.append(model.model)
        assert old_id in {thread['id'] for thread in task['threads']}
        if calls == ['primary', 'review']:
            raise TimeoutError('Simulated review outage')
        if task.get('task_type') == 'topic_decisions':
            return {'decisions': [{'index': 0, 'action': 'existing', 'thread_id': old_id,
                    'reason': 'Same issue with actual progress', 'status': 'in_progress'}]}, 7
        return {'items': [item(2, thread_id=old_id, link_reason='Same issue followup',
                               status='in_progress')]}, 20

    kwargs = dict(feature='extraction', kind='batch', records=[record(2, day=2)],
                  request=request, model=PRIMARY)
    assert knowledge.analyze(path, SCOPE, **kwargs)['status'] == 'review_failed'
    # Synthetic source records deliberately have no bot.db copy: the model input
    # stays identical while the current candidate window changes independently.
    for mid in range(3, 16):
        db.finish(f'new-{mid}', SCOPE, {'items': [item(mid)]}, 1, extraction=True,
                  glossary=False, track_topics=True, records=[record(mid, day=mid)])
    assert old_id not in {thread['id'] for thread in db.thread_candidates(SCOPE)}
    result = knowledge.analyze(path, SCOPE, **kwargs)
    assert result['status'] == 'completed' and result['reviewed']
    assert calls == ['primary', 'review', 'review', 'review']
    original = next(thread for thread in db.threads(SCOPE) if thread['id'] == old_id)
    assert len(original['events']) == 2
    assert original['status'] == 'in_progress'


def test_disabling_inference_keeps_prior_annotation_and_never_supplies_it_as_active(tmp_path):
    path, db = configured(tmp_path, infer=True)
    calls = []

    def request(messages, model):
        task = json.loads(messages[1]['content'])
        calls.append(task)
        assert task['glossary'] == []
        ids = [row['id'] for row in task['messages']]
        return {'terms': [{'term': 'Starflow', 'meaning': 'A local parameter',
            'evidence_ids': ids, 'inference_kind': 'inferred',
            'inference_note': 'Two original usage examples',
            'inference_evidence': [{'message_id': row['id'], 'quote': row['text']}
                                   for row in task['messages']]}]}, 20

    knowledge.analyze(path, SCOPE, feature='glossary', kind='manual:glossary', model=PRIMARY,
                      records=[record(1, text='Starflow changes the image'),
                               record(2, text='Starflow is adjusted in settings')], request=request)
    original = db.terms(SCOPE)[0]
    assert original['inference_kind'] == 'inferred' and original['status'] == 'candidate'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['knowledge']['groups'][SCOPE]['glossary']['infer_context'] = False
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    knowledge.analyze(path, SCOPE, feature='glossary', kind='manual:glossary', model=PRIMARY,
                      records=[record(3, text='Starflow needs another test'),
                               record(4, text='Starflow settings remain unchanged')], request=request)
    saved = db.terms(SCOPE)[0]
    assert calls[-1]['capabilities']['infer_context'] is False
    assert saved['status'] == 'candidate' and saved['inference_kind'] == 'inferred'
    assert saved['inference_note'] == original['inference_note']
    assert saved['inference_evidence'] == original['inference_evidence']


def test_rejected_resolution_is_consistent_in_result_database_and_topic_view(tmp_path):
    path, db = configured(tmp_path)
    proposed = item(1, status='resolved', value='high', evidence_state='verified',
                    category='knowledge', resolution_evidence=[
                        {'message_id': 1, 'quote': 'Fabricated successful outcome'}])
    result = knowledge.analyze(path, SCOPE, feature='extraction', kind='manual:extraction',
        records=[record(1, text='Still waiting for an actual test result')], model=PRIMARY,
        request=lambda *_: ({'items': [proposed]}, 20))
    expected = dict(status='in_progress', value='candidate', evidence_state='reported',
                    category='question')
    for key, value in expected.items():
        assert result['items'][0][key] == value
    with db.conn() as conn:
        stored_result = json.loads(conn.execute(
            "SELECT result_json FROM runs WHERE status='completed'").fetchone()[0])
    for key, value in expected.items():
        assert stored_result['items'][0][key] == value
    stored_item = db.items(SCOPE)[0]
    for key in ('value', 'evidence_state', 'category'):
        assert stored_item[key] == expected[key]
    thread = db.threads(SCOPE)[0]
    for key in ('status', 'value', 'category'):
        assert thread[key] == expected[key]
    assert thread['events'][0]['requested_status'] == 'resolved'
    assert thread['events'][0]['status_reason']
    page = (db.path.parent / 'view/knowledge.html').read_text(encoding='utf-8')
    card = re.search(r'(<article[^>]*><h2>Issue 1</h2>.*?</article>)', page, re.S).group(1)
    assert 'data-value="candidate"' in card and 'data-category="question"' in card
    assert '原消息有解决反馈' not in card

import copy
import json
from pathlib import Path
import sqlite3

import pytest

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist import knowledge_subject_review as review


SCOPE = 'group:123'
MODEL = LLMConfig('https://primary.invalid/v1', 'never-persist-this-secret', 'workbuddy-test')


def prepared(tmp_path, monkeypatch, count=3, budget=50000):
    config = AppConfig(data_dir=tmp_path, source_path=tmp_path / 'config.yaml',
        ai_context_provider='freehy', ai_context_provider_explicit=True,
        ai_context_providers={'freehy': {'base_url': MODEL.base_url, 'model': MODEL.model,
                                       'api_key_env': 'TEST_ONLY'}},
        knowledge={'enabled': True, 'defaults': {'max_tokens_per_day': budget,
            'models': {'tiered_enabled': True, 'primary_provider': 'freehy',
                       'fallback_provider': 'ds_v4_flash'}},
            'groups': {SCOPE: {'enabled': True, 'extraction': {'enabled': True}}}})
    monkeypatch.setattr(review, 'load_config', lambda _: config)
    # Tests must never resolve a credential or open a network connection.
    monkeypatch.setattr(review, 'resolve_models', lambda *_: pytest.fail('unexpected credential resolution'))
    with sqlite3.connect(tmp_path / 'bot.db') as conn:
        conn.execute('''CREATE TABLE messages(id INTEGER PRIMARY KEY,scope TEXT,user_id TEXT,
            text TEXT,raw_json TEXT,seen_at TEXT,links_json TEXT,message_key TEXT)''')
        for mid in range(1, 5):
            conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)',
                         (mid, SCOPE, '7', 'WorkBuddy 调整节点后正常了。' + '原文' * 100,
                          json.dumps({'time': 1791777600, 'message_id': mid}), 'now', '[]', str(mid)))
        conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)',
                     (99, 'group:456', '7', 'GPT 在其他群', '{}', 'now', '[]', '99'))
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    with db.conn() as conn:
        for index in range(count):
            conn.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (f'item-{index}', SCOPE, 'now', f'节点排错 {index}', '知识正文' * 100,
                          '排错', '软件使用', 'candidate', '[1,2,3,4]', '[]', 'reported'))
            org = {'topics': ['development'], 'subject': {'name': '对象未知', 'ambiguous': True},
                   'retention_class': 'detailed', 'progress_kind': 'unknown'}
            conn.execute('INSERT INTO item_organization VALUES (?,?)',
                         (f'item-{index}', json.dumps(org, ensure_ascii=False)))
        conn.execute('INSERT INTO cursors VALUES (?,?,?,?)', (SCOPE, 'batch', 888, 'now'))
        conn.execute('INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)',
                     ('term', SCOPE, '术语', '原释义', '[1]', 'candidate', '[]', 'ai'))
    return config, db


def answer(messages, model, *, max_tokens):
    assert model is MODEL
    assert max_tokens == 2500
    task = json.loads(messages[1]['content'])
    return {'decisions': [{'key': row['key'], 'subjects': [{'name': 'wb', 'evidence': [
        {'message_id': 1, 'quote': 'WorkBuddy 调整节点后正常了。'}]}]} for row in task['items']]}, 80


def annotations(db):
    with db.conn() as conn:
        return {row[0]: json.loads(row[1]) for row in conn.execute('SELECT * FROM item_organization')}


def runs(db):
    with db.conn() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM runs ORDER BY created_at,key')]


def test_explicit_review_preserves_knowledge_and_runtime_and_reuses_completed_annotations(tmp_path, monkeypatch):
    config, db = prepared(tmp_path, monkeypatch)
    before = annotations(db)
    with db.conn() as conn:
        untouched = {table: [tuple(row) for row in conn.execute('SELECT * FROM ' + table)]
                     for table in ('items', 'terms', 'cursors', 'knowledge_threads', 'knowledge_thread_events')}
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        return answer(*args, **kwargs)
    result = review.review_subjects('unused', SCOPE, batch_size=2, request=request, model=MODEL)
    assert result['status'] == 'completed' and result['processed'] == 3 and result['remaining'] == 0
    assert len(calls) == 2
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1
    with sqlite3.connect(result['backup']) as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
        assert 'subjects_version' not in conn.execute('SELECT organization_json FROM item_organization').fetchone()[0]
    after = annotations(db)
    for key, org in after.items():
        assert org['subjects_version'] == 1 and org['subjects'][0]['name'] == 'WorkBuddy'
        assert org['subjects_complete'] is True
        assert {k: v for k, v in org.items() if k not in ('subjects', 'subjects_version', 'subjects_complete')} == before[key]
    with db.conn() as conn:
        for table, rows in untouched.items():
            assert [tuple(row) for row in conn.execute('SELECT * FROM ' + table)] == rows
    for run in runs(db):
        assert run['status'] == 'completed' and run['kind'] == 'model:subjects' and run['tokens'] == 80
        audit = json.loads(run['result_json'])
        assert audit['_source_hashes'] and audit['_task']['items'] and audit['decisions']
        assert MODEL.api_key not in json.dumps(run)
    again = review.review_subjects('unused', SCOPE, request=lambda *_: pytest.fail('AI repeated'), model=MODEL)
    assert again['status'] == 'unchanged' and again['processed'] == 0
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_model_input_covers_all_evidence_including_late_product_names(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1)
    def request(messages, model, **kwargs):
        task = json.loads(messages[1]['content'])
        row = task['items'][0]
        assert len(row['title']) <= 180 and len(row['body']) == 180
        assert [message['message_id'] for message in row['messages']] == [1, 2, 3, 4]
        assert all(len(message['text']) > 120 for message in row['messages'])
        assert row['existing_subject'] == '对象未知' and 'WorkBuddy' in task['catalog']
        # Unknown means all available evidence was actually sent to the model.
        return {'decisions': [{'key': row['key'], 'subjects': []}]}, None
    result = review.review_subjects('unused', SCOPE, request=request, model=MODEL)
    assert result['status'] == 'completed' and annotations(db)['item-0']['subjects'] == []
    run = runs(db)[0]
    assert run['tokens'] > 2500 and json.loads(run['result_json'])['token_usage_estimated']


def test_product_only_in_middle_evidence_or_after_old_excerpt_is_available(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1)
    with sqlite3.connect(tmp_path / 'bot.db') as conn:
        conn.execute("UPDATE messages SET text='无对象的普通消息' WHERE scope=?", (SCOPE,))
        conn.execute('UPDATE messages SET text=? WHERE id=3', ('原文' * 100 + ' GLM5.3额度',))
    def request(messages, model, **kwargs):
        task = json.loads(messages[1]['content'])
        row = task['items'][0]
        assert row['messages'][2]['message_id'] == 3
        assert 'GLM5.3' in row['messages'][2]['text']
        return {'decisions': [{'key': row['key'], 'subjects': [{'name': '智谱',
            'evidence': [{'message_id': 3, 'quote': 'GLM5.3'}]}]}]}, 80
    assert review.review_subjects('unused', SCOPE, request=request, model=MODEL)['status'] == 'completed'
    assert annotations(db)['item-0']['subjects'][0]['name'] == '智谱'


@pytest.mark.parametrize('disabled', ['global', 'group', 'extraction', 'blocked'])
def test_disabled_review_has_no_database_backup_or_ai_side_effects(tmp_path, monkeypatch, disabled):
    config = AppConfig(data_dir=tmp_path / 'never-created', knowledge={'enabled': True,
        'groups': {SCOPE: {'enabled': True, 'extraction': {'enabled': True}}}})
    if disabled == 'global': config.knowledge['enabled'] = False
    elif disabled == 'group': config.knowledge['groups'][SCOPE]['enabled'] = False
    elif disabled == 'extraction': config.knowledge['groups'][SCOPE]['extraction']['enabled'] = False
    else: config.blocked_groups.add('123')
    monkeypatch.setattr(review, 'load_config', lambda _: config)
    monkeypatch.setattr(review, 'resolve_models', lambda *_: pytest.fail('resolved disabled model'))
    assert review.review_subjects('unused', SCOPE)['status'] == 'disabled'
    assert not config.data_dir.exists()


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'unknown', 'wrong-format', 'unknown-product',
                               'wrong-quote', 'cross-group', 'mixed-valid-invalid', 'too-many'])
def test_invalid_batch_cannot_partially_publish(tmp_path, monkeypatch, bad):
    _, db = prepared(tmp_path, monkeypatch, count=2)
    original = annotations(db)
    def request(*args, **kwargs):
        value, usage = answer(*args, **kwargs)
        decisions = value['decisions']
        if bad == 'missing': decisions.pop()
        elif bad == 'duplicate': decisions[1]['key'] = decisions[0]['key']
        elif bad == 'unknown': decisions[1]['key'] = 'missing-key'
        elif bad == 'wrong-format': decisions[1]['subjects'] = None
        elif bad == 'unknown-product': decisions[1]['subjects'][0]['name'] = 'GPT'
        elif bad == 'wrong-quote': decisions[1]['subjects'][0]['evidence'][0]['quote'] = 'WorkBuddy invented'
        elif bad == 'cross-group': decisions[1]['subjects'][0]['evidence'][0]['message_id'] = 99
        elif bad == 'mixed-valid-invalid':
            decisions[1]['subjects'][0]['evidence'].append({'message_id': 99, 'quote': 'other'})
        else: decisions[1]['subjects'] *= 4
        return value, usage
    result = review.review_subjects('unused', SCOPE, request=request, model=MODEL)
    assert result['status'] == 'failed' and result['processed'] == 0 and result['remaining'] == 2
    assert annotations(db) == original
    assert runs(db)[0]['status'] == 'failed' and runs(db)[0]['tokens'] > 2500


@pytest.mark.parametrize('change', ['organization', 'title', 'body', 'evidence', 'source',
                                   'global', 'group', 'extraction', 'provider'])
def test_concurrent_changes_are_not_overwritten(tmp_path, monkeypatch, change):
    config, db = prepared(tmp_path, monkeypatch, count=2)
    original = annotations(db)
    def request(*args, **kwargs):
        if change in ('organization', 'title', 'body', 'evidence'):
            with db.conn() as conn:
                if change == 'organization':
                    conn.execute("UPDATE item_organization SET organization_json=? WHERE item_key='item-1'",
                                 (json.dumps({'human': 'kept'}),))
                else:
                    column = 'evidence_json' if change == 'evidence' else change
                    value = '[1]' if change == 'evidence' else 'human edit'
                    conn.execute(f"UPDATE items SET {column}=? WHERE key='item-1'", (value,))
        elif change == 'source':
            with sqlite3.connect(tmp_path / 'bot.db') as conn:
                conn.execute("UPDATE messages SET text='human source edit' WHERE id=1")
        elif change == 'global': config.knowledge['enabled'] = False
        elif change == 'group': config.knowledge['groups'][SCOPE]['enabled'] = False
        elif change == 'extraction': config.knowledge['groups'][SCOPE]['extraction']['enabled'] = False
        else: config.ai_context_providers['freehy']['base_url'] = 'https://changed.invalid'
        return answer(*args, **kwargs)
    result = review.review_subjects('unused', SCOPE, request=request, model=MODEL)
    assert result['status'] == 'failed' and result['processed'] == 0
    assert annotations(db)['item-0'] == original['item-0']
    if change == 'organization': assert annotations(db)['item-1'] == {'human': 'kept'}
    else: assert annotations(db) == original
    assert runs(db)[0]['status'] == 'failed' and runs(db)[0]['tokens'] > 2500


def test_missing_original_message_is_refused_before_ai(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1)
    with db.conn() as conn: conn.execute('UPDATE items SET evidence_json=?', ('[99]',))
    result = review.review_subjects('unused', SCOPE, request=lambda *_: pytest.fail('AI called'), model=MODEL)
    assert result['status'] == 'failed' and not runs(db) and not (tmp_path / 'backups').exists()


def test_budget_is_enforced_before_model_request(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1, budget=1000)
    result = review.review_subjects('unused', SCOPE, request=lambda *_: pytest.fail('budget exceeded'), model=MODEL)
    assert result['status'] == 'partial' and result['processed'] == 0 and result['remaining'] == 1
    assert not runs(db)


def test_failed_requests_keep_reservation_and_never_call_fallback(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1)
    selected = []
    def resolve(settings):
        assert settings['_default_provider'] == 'freehy'
        assert settings['models']['primary_provider'] == 'freehy'
        assert not settings['models']['fallback_provider']
        return [MODEL, LLMConfig('https://fallback.invalid', 'fallback', 'DS')]
    monkeypatch.setattr(review, 'resolve_models', resolve)
    def request(messages, model, **kwargs):
        selected.append(model)
        raise RuntimeError('secret response: ' + MODEL.api_key)
    result = review.review_subjects('unused', SCOPE, request=request)
    assert selected == [MODEL] and result['status'] == 'failed'
    assert result['error'] == 'RuntimeError' and MODEL.api_key not in json.dumps(result)
    assert runs(db)[0]['tokens'] > 2500 and runs(db)[0]['error'] == 'RuntimeError'


def test_default_request_uses_knowledge_model_request_with_completion_limit(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=1)
    monkeypatch.setattr('qq_onebot_whitelist.knowledge.model_request', answer)
    assert review.review_subjects('unused', SCOPE, model=MODEL)['status'] == 'completed'
    assert runs(db)[0]['tokens'] == 80


def test_batch_limit_and_resuming_only_review_remaining_items(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=3)
    first = review.review_subjects('unused', SCOPE, max_batches=1, batch_size=2, request=answer, model=MODEL)
    assert first['status'] == 'partial' and first['processed'] == 2 and first['remaining'] == 1
    second = review.review_subjects('unused', SCOPE, request=answer, model=MODEL)
    assert second['status'] == 'completed' and second['processed'] == 1
    assert len(runs(db)) == 2


def test_atomic_write_failure_rolls_back_all_annotations(tmp_path, monkeypatch):
    _, db = prepared(tmp_path, monkeypatch, count=2)
    before = annotations(db)
    with db.conn() as conn:
        conn.execute('''CREATE TRIGGER refuse_second BEFORE INSERT ON item_organization
            WHEN NEW.item_key='item-1' BEGIN SELECT RAISE(ABORT,'test rejection'); END''')
    result = review.review_subjects('unused', SCOPE, request=answer, model=MODEL)
    assert result['status'] == 'failed' and annotations(db) == before
    assert runs(db)[0]['status'] == 'failed'


def test_key_identity_excludes_credentials_but_includes_model(tmp_path, monkeypatch):
    identities = []
    for index, (secret, name) in enumerate([('first-secret', 'same'), ('second-secret', 'same'), ('first-secret', 'other')]):
        directory = tmp_path / str(index)
        directory.mkdir()
        _, db = prepared(directory, monkeypatch, count=1)
        model = LLMConfig(MODEL.base_url, secret, name)
        def request(messages, selected, **kwargs):
            task = json.loads(messages[1]['content'])
            return {'decisions': [{'key': row['key'], 'subjects': []} for row in task['items']]}, 80
        assert review.review_subjects('unused', SCOPE, request=request, model=model)['status'] == 'completed'
        identities.append(runs(db)[0]['key'])
    assert identities[0] == identities[1] and identities[0] != identities[2]

from copy import deepcopy
import json

import pytest
import yaml

from qq_onebot_whitelist import knowledge
from qq_onebot_whitelist.knowledge_models import CircuitBreaker
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.llm_summary import LLMConfig


PRIMARY = LLMConfig('https://primary.invalid/v1', 'primary-private-key', 'primary')
FALLBACK = LLMConfig('https://fallback.invalid/v1', 'fallback-private-key', 'fallback')
REVIEW = LLMConfig('https://review.invalid/v1', 'review-private-key', 'review')


def configured(tmp_path, *, models=None, defaults=None, files=None, budget=100000):
    group = {'enabled': True, 'summary': {'enabled': True}, 'extraction': {'enabled': True},
             'history': {'enabled': True}, 'max_tokens_per_day': budget}
    if models is not None:
        group['models'] = models
    if files is not None:
        group['files'] = files
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(tmp_path / 'data')},
        'knowledge': {'enabled': True, 'defaults': defaults or {}, 'groups': {'group:123': group}}}), encoding='utf-8')
    return path


def rows(mid=1, *, file=False):
    return [{'id': mid, 'scope': 'group:123', 'text': '节点问题已调整并验证恢复', 'time': None,
             'quoted_id': None, 'quoted_text': '', 'links': [], 'segments': ['text'],
             'files': [{'file_id': 'f1', 'file_name': 'workflow.json', 'file_size': 50,
                        'scope': 'group:123', 'message_id': mid}] if file else []}]


def output(material, *, candidate=False):
    evidence = [r['id'] for r in material['messages'] if not r.get('context_only')]
    return {'summary': [{'text': '调整后恢复', 'evidence_ids': evidence}],
            'items': [{'title': '节点排错', 'summary': '证据说明调整后恢复', 'kind': '排错',
                       'topic': 'AI绘图', 'value': 'candidate' if candidate else 'high',
                       'evidence_state': 'reported', 'evidence_ids': evidence,
                       'file_ids': ['f1'] if material['messages'][0]['files'] else []}], 'terms': []}


@pytest.fixture(autouse=True)
def no_environment_or_view(monkeypatch):
    monkeypatch.setattr(LLMConfig, 'from_env', lambda: PRIMARY)
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file', lambda: FALLBACK)
    monkeypatch.setattr(knowledge, 'write_view', lambda *args: None)


def test_inherited_true_model_options_are_inactive(tmp_path, monkeypatch):
    path = configured(tmp_path, defaults={'models': {'circuit_enabled': True, 'review_enabled': True,
                'tiered_enabled': True, 'primary_model': 'inherited-cheap'}})
    monkeypatch.setattr(knowledge, 'CircuitBreaker', lambda *a: pytest.fail('inherited breaker opt-in'))
    calls = []
    def request(messages, cfg):
        calls.append(cfg.model)
        return output(json.loads(messages[1]['content'])), 20
    result = knowledge.analyze(path, '123', records=rows(), kind='batch', request=request)
    assert result['status'] == 'completed' and calls == ['primary']
    assert not result.get('reviewed')
    assert not (tmp_path / 'data' / 'knowledge-model-health.db').exists()


def test_cooling_primary_is_skipped_before_budget_claim(tmp_path, monkeypatch):
    path = configured(tmp_path, models={'circuit_enabled': True, 'failure_threshold': 1, 'cooldown_seconds': 300})
    breaker = CircuitBreaker(tmp_path / 'data' / 'knowledge-model-health.db')
    assert breaker.permit(PRIMARY, threshold=1, cooldown=300)
    breaker.failure(PRIMARY)
    events = []
    original_claim = KnowledgeDB.claim
    def claim(self, *args, **kwargs):
        events.append('claim')
        return original_claim(self, *args, **kwargs)
    monkeypatch.setattr(KnowledgeDB, 'claim', claim)
    def request(messages, cfg):
        events.append(cfg.model)
        return output(json.loads(messages[1]['content'])), 20
    result = knowledge.analyze(path, '123', records=rows(), request=request)
    assert events == ['claim', 'fallback']
    assert result['model'] == 'fallback'
    with KnowledgeDB(tmp_path / 'data' / 'knowledge.db').conn() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1


def test_provider_failures_have_independent_reservations(tmp_path):
    path = configured(tmp_path, models={'circuit_enabled': True, 'failure_threshold': 1})
    def request(messages, cfg):
        if cfg.model == 'primary':
            raise TimeoutError('https://signed.invalid?key=primary-private-key')
        return output(json.loads(messages[1]['content'])), 30
    result = knowledge.analyze(path, '123', records=rows(), request=request)
    assert result['status'] == 'completed'
    with KnowledgeDB(tmp_path / 'data' / 'knowledge.db').conn() as conn:
        attempts = [dict(r) for r in conn.execute('SELECT * FROM runs')]
    assert len(attempts) == 2 and len({a['key'] for a in attempts}) == 2
    failed = next(a for a in attempts if a['status'] == 'failed')
    assert failed['tokens'] > 6000 and failed['error'] == 'TimeoutError'
    assert 'primary-private-key' not in json.dumps(attempts)
    states = CircuitBreaker(tmp_path / 'data' / 'knowledge-model-health.db').snapshot()
    assert next(s for s in states if s['model'] == 'primary')['state'] == 'open'
    assert next(s for s in states if s['model'] == 'fallback')['state'] == 'closed'


def test_review_failure_caches_primary_without_persisting_items_or_files(tmp_path, monkeypatch):
    path = configured(tmp_path, models={'review_enabled': True}, files={'enabled': True})
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW)
    saved = []
    monkeypatch.setattr(knowledge, 'retain_selected_files', lambda *a: saved.append(1))
    calls = []
    def request(messages, cfg):
        calls.append(cfg.model)
        if cfg.model == 'review':
            raise TimeoutError('private-review-body')
        return output(json.loads(messages[1]['content'])), 50
    result = knowledge.analyze(path, '123', feature='extraction', kind='batch', records=rows(file=True), request=request)
    db = KnowledgeDB(tmp_path / 'data' / 'knowledge.db')
    assert result['status'] == 'review_failed' and calls == ['primary', 'review']
    assert not db.items('group:123') and not saved
    assert db.cursor('group:123', 'live') == (0, None)
    assert 'private-review-body' not in json.dumps(result)


def test_review_retry_reuses_primary_and_charges_each_stage_once(tmp_path, monkeypatch):
    path = configured(tmp_path, models={'review_enabled': True})
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW)
    calls = []
    def request(messages, cfg):
        calls.append(cfg.model)
        material = json.loads(messages[1]['content'])
        if cfg.model == 'review':
            assert 'preliminary_result' in material
            assert '独立复核' in messages[0]['content']
            if calls.count('review') == 1:
                raise TimeoutError()
            return output(material, candidate=True), 70
        return output(material), 50
    assert knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)['status'] == 'review_failed'
    result = knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)
    assert calls == ['primary', 'review', 'review']
    assert result['reviewed'] and result['tokens'] == 120
    assert result['primary_model'] == 'primary' and result['review_model'] == 'review'
    assert result['items'][0]['value'] == 'candidate'
    db = KnowledgeDB(tmp_path / 'data' / 'knowledge.db')
    with db.conn() as conn:
        assert conn.execute("SELECT sum(tokens) FROM runs WHERE status='completed'").fetchone()[0] == 120
        assert conn.execute("SELECT count(*) FROM runs WHERE status='failed'").fetchone()[0] == 1
    cached = knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)
    assert cached['cached'] and len(calls) == 3


def test_review_budget_shortage_retries_without_repeating_primary(tmp_path, monkeypatch):
    # Enough for the expanded classification/background primary prompt, then
    # deliberately leave too little for an independent review reservation.
    path = configured(tmp_path, models={'review_enabled': True}, budget=30000)
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW)
    calls = []
    def request(messages, cfg):
        calls.append(cfg.model)
        return output(json.loads(messages[1]['content'])), 28000 if cfg.model == 'primary' else 70
    assert knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)['status'] == 'review_failed'
    assert calls == ['primary']
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups']['group:123']['max_tokens_per_day'] = 100000
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    result = knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)
    assert result['status'] == 'completed' and calls == ['primary', 'review']


def test_review_uses_evidence_validator(tmp_path, monkeypatch):
    path = configured(tmp_path, models={'review_enabled': True})
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW)
    def request(messages, cfg):
        result = output(json.loads(messages[1]['content']))
        if cfg.model == 'review':
            result['items'][0]['evidence_ids'] = [9999]
        return result, 20
    assert knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)['status'] == 'review_failed'
    assert not KnowledgeDB(tmp_path / 'data' / 'knowledge.db').items('group:123')


def test_model_policy_change_invalidates_cache(tmp_path):
    path = configured(tmp_path)
    calls = []
    def request(messages, cfg):
        calls.append(cfg.model)
        return output(json.loads(messages[1]['content'])), 20
    knowledge.analyze(path, '123', records=rows(), request=request)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups']['group:123']['models'] = {'tiered_enabled': True, 'primary_model': 'explicit-cheap-id'}
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    result = knowledge.analyze(path, '123', records=rows(), request=request)
    assert result['model'] == 'explicit-cheap-id' and calls == ['primary', 'explicit-cheap-id']


def test_previews_are_material_budgeted_and_not_repeated_for_cache(tmp_path, monkeypatch):
    from qq_onebot_whitelist import knowledge_file_material
    path = configured(tmp_path, files={'enabled': True, 'preview_enabled': True})
    previews = []
    def prepare(config_path, scope, records):
        previews.append(1)
        result = deepcopy(records)
        result[0]['files'][0]['preview'] = {'status': 'ready', 'text': 'bounded preview evidence', 'sha256': 'safehash'}
        return result
    monkeypatch.setattr(knowledge_file_material, 'prepare_file_previews', prepare)
    monkeypatch.setattr(knowledge, 'retain_selected_files', lambda *a: None)
    reserves = []
    original_claim = KnowledgeDB.claim
    def claim(self, key, scope, kind, reserve, *args):
        reserves.append(reserve)
        return original_claim(self, key, scope, kind, reserve, *args)
    monkeypatch.setattr(KnowledgeDB, 'claim', claim)
    def request(messages, cfg):
        material = json.loads(messages[1]['content'])
        assert material['messages'][0]['files'][0]['preview']['text'] == 'bounded preview evidence'
        assert reserves[-1] == len(json.dumps(messages, ensure_ascii=False).encode()) + knowledge.MAX_COMPLETION + 256
        return output(material), 30
    result = knowledge.analyze(path, '123', kind='batch', records=rows(file=True), request=request)
    assert result['status'] == 'completed'
    assert knowledge.analyze(path, '123', kind='batch', records=rows(file=True), request=request)['cached']
    assert previews == [1] and len(reserves) == 1


def test_review_disable_during_request_prevents_completion(tmp_path, monkeypatch):
    path = configured(tmp_path, models={'review_enabled': True})
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW)
    def request(messages, cfg):
        if cfg.model == 'review':
            raw = yaml.safe_load(path.read_text(encoding='utf-8'))
            raw['knowledge']['groups']['group:123']['models']['review_enabled'] = False
            path.write_text(yaml.safe_dump(raw), encoding='utf-8')
        return output(json.loads(messages[1]['content'])), 20
    assert knowledge.analyze(path, '123', kind='batch', records=rows(), request=request)['status'] == 'disabled'
    assert not KnowledgeDB(tmp_path / 'data' / 'knowledge.db').items('group:123')


@pytest.mark.parametrize('review', [False, True])
def test_rejected_claim_does_not_fail_another_running_attempt(tmp_path, monkeypatch, review):
    path = configured(tmp_path, models={'review_enabled': review})
    monkeypatch.setattr(knowledge, 'resolve_review_model', lambda *a: REVIEW if review else None)
    original_claim = KnowledgeDB.claim
    failures = []
    def claim(self, key, scope, kind, *args):
        if not review or not kind.startswith('model:primary:'):
            raise RuntimeError('同一分析任务正在运行')
        return original_claim(self, key, scope, kind, *args)
    monkeypatch.setattr(KnowledgeDB, 'claim', claim)
    monkeypatch.setattr(KnowledgeDB, 'fail', lambda self, key, error: failures.append((key, error)))
    def request(messages, cfg):
        return output(json.loads(messages[1]['content'])), 20
    if review:
        assert knowledge.analyze(path, '123', records=rows(), request=request)['status'] == 'review_failed'
    else:
        with pytest.raises(RuntimeError):
            knowledge.analyze(path, '123', records=rows(), request=request)
    assert failures == []


def test_exhausted_budget_skips_preview_downloads(tmp_path, monkeypatch):
    from qq_onebot_whitelist import knowledge_file_material
    path = configured(tmp_path, files={'enabled': True, 'preview_enabled': True}, budget=1000)
    monkeypatch.setattr(knowledge_file_material, 'prepare_file_previews', lambda *a: pytest.fail('budget exhausted before preview'))
    with pytest.raises(RuntimeError):
        knowledge.analyze(path, '123', kind='batch', records=rows(file=True), request=lambda *a: pytest.fail('no budget'))


def test_multiple_previews_on_single_message_obey_material_byte_limit(tmp_path, monkeypatch):
    from qq_onebot_whitelist import knowledge_file_material
    path = configured(tmp_path, files={'enabled': True, 'preview_enabled': True})
    sources = rows(file=True)
    sources[0]['files'] += [{**sources[0]['files'][0], 'file_id': fid} for fid in ('f2', 'f3')]
    def prepare(config_path, scope, records):
        records = deepcopy(records)
        for file in records[0]['files']:
            file['preview'] = {'status': 'ready', 'text': '中文材料' * 1500}
        return records
    monkeypatch.setattr(knowledge_file_material, 'prepare_file_previews', prepare)
    monkeypatch.setattr(knowledge, 'retain_selected_files', lambda *a: None)
    def request(messages, cfg):
        material = json.loads(messages[1]['content'])
        assert len(json.dumps(material['messages'], ensure_ascii=False).encode()) <= 26000
        assert any(f['preview'].get('truncated') for f in material['messages'][0]['files'])
        return output(material), 20
    assert knowledge.analyze(path, '123', kind='batch', records=sources, request=request)['status'] == 'completed'

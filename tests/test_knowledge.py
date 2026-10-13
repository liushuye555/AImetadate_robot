import json
import sqlite3
from datetime import datetime, timedelta

import pytest
import yaml

from qq_onebot_whitelist.config import AppConfig, load_config
from qq_onebot_whitelist.knowledge import analyze, automatic_tick, command_reply, history, retry_files, summarize_range, validate_result, write_view
from qq_onebot_whitelist.knowledge_config import enabled_profiles, profile_for
from qq_onebot_whitelist.knowledge_store import KnowledgeDB, LOCAL_TZ, date_bounds, read_records
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist.store import Store


MODEL = LLMConfig('https://model.invalid/v1', 'test-key', 'test-model')


def configured(tmp_path, features=('summary', 'extraction', 'glossary'), **settings):
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    profile = {'enabled': True, 'topics': ['ai_drawing'], 'batch_size': 5,
               **{f: {'enabled': True} for f in features}, **settings}
    raw = {'storage': {'data_dir': str(data)}, 'knowledge': {'enabled': True, 'groups': {'group:123': profile}}}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding='utf-8')
    return path, Store(data / 'bot.db')


def record(store, text='调整节点后正常了', time='2026-10-12T12:00:00+08:00', mid=1, scope='group:123', reply=None, file=None):
    segments = [{'type': 'text', 'data': {'text': text}}]
    if reply:
        segments.append({'type': 'reply', 'data': {'id': reply}})
    if file:
        segments.append({'type': 'file', 'data': file})
    raw = dict(time=int(datetime.fromisoformat(time).timestamp()), message_id=mid, message=segments)
    store.record_message(scope=scope, user_id='10', text=text, raw=raw)


def response(ids, *, summary=True, files=None):
    return {'summary': [{'text': '节点调整后恢复，群友反馈有效。', 'evidence_ids': ids}] if summary else [],
            'items': [{'title': '节点排错', 'summary': '调整节点后恢复；具体版本未提供。',
                       'kind': '排错', 'topic': 'AI绘图', 'value': 'high', 'evidence_ids': ids, 'file_ids': files or []}],
            'terms': [{'term': '跑图', 'meaning': '生成图像', 'evidence_ids': ids}]}


def request(messages, model):
    rows = json.loads(messages[1]['content'])['messages']
    return response([r['id'] for r in rows]), 80


@pytest.mark.parametrize('raw', [{}, {'enabled': True}, {'enabled': True, 'groups': {'group:123': {'enabled': True}}},
                                    {'enabled': 'true', 'groups': {'group:123': {'enabled': True, 'summary': {'enabled': True}}}}])
def test_default_gates_do_not_create_database_or_read_credentials(tmp_path, monkeypatch, raw):
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'storage': {'data_dir': str(tmp_path / 'data')}, 'knowledge': raw}), encoding='utf-8')
    monkeypatch.setattr(LLMConfig, 'from_env', lambda: pytest.fail('disabled must not read credentials'))
    assert analyze(path, '123')['status'] == 'disabled'
    assert not (tmp_path / 'data').exists()
    assert automatic_tick(path) == []
    assert not (tmp_path / 'data').exists()


def test_features_must_be_explicit_in_group_and_blocked_groups_win():
    cfg = AppConfig(knowledge={'enabled': True, 'defaults': {'enabled': True, 'summary': {'enabled': True}},
                               'groups': {'group:123': {'enabled': True, 'extraction': {'enabled': True}}}})
    assert not profile_for(cfg, '123').allows('summary')
    assert profile_for(cfg, '123').allows('extraction')
    assert not profile_for(cfg, '999').allows('extraction')
    cfg.blocked_groups.add('123')
    assert enabled_profiles(cfg) == []


def test_date_uses_original_time_and_quotes_stay_in_group(tmp_path):
    path, store = configured(tmp_path)
    record(store, '另一个群的秘密', mid=77, scope='group:999')
    record(store, '旧问题', time='2026-06-01T12:00:00+08:00', mid=77)
    record(store, reply='77', mid=78)
    records = read_records(store.path, 'group:123', bounds=date_bounds('2026-10-12'))
    assert len(records) == 1
    assert records[0]['quoted_text'] == '旧问题'
    assert records[0]['time'].startswith('2026-10-12')
    assert records[0]['quoted_id'] == 2
    assert read_records(store.path, 'group:123', bounds=date_bounds('2026-06-01'))[0]['text'] == '旧问题'


def test_plain_text_and_pdf_are_material_without_keyword_gate(tmp_path):
    path, store = configured(tmp_path)
    record(store, '这样就好了', file={'name': '资料.pdf', 'id': 'fid-1', 'size': 9})
    records = read_records(store.path, 'group:123')
    assert records[0]['files'][0]['file_name'] == '资料.pdf'
    result = analyze(path, '123', request=request, model=MODEL, kind='batch')
    assert result['status'] == 'completed'
    assert len(KnowledgeDB(store.path.parent / 'knowledge.db').items('group:123')) == 1


def test_independent_manual_summary_does_not_create_knowledge_or_terms(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    result = analyze(path, '123', request=request, model=MODEL)
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    assert result['summary']
    assert result['items'] == [] and result['terms'] == []
    assert db.items('group:123') == [] and db.terms('group:123') == []


def test_idempotent_analysis_reuses_result_after_knowledge_has_changed(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    calls = []
    def tracked(messages, model):
        calls.append(1)
        return request(messages, model)
    first = analyze(path, '123', feature='extraction', kind='batch', request=tracked, model=MODEL)
    second = analyze(path, '123', feature='extraction', kind='batch', request=tracked, model=MODEL)
    assert first['status'] == second['status'] == 'completed'
    assert second['cached'] and len(calls) == 1


def test_rejects_foreign_or_invented_evidence_and_keeps_failed_run(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    with pytest.raises(RuntimeError):
        analyze(path, '123', feature='extraction', kind='batch', request=lambda *a: (response([999]), 20), model=MODEL)
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    assert not db.items('group:123')
    with db.conn() as conn:
        assert conn.execute('SELECT status FROM runs').fetchone()[0] == 'failed'
    assert db.cursor('group:123', 'live') == (0, None)


def test_disabling_during_model_call_prevents_persistence(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    def changed(messages, model):
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        raw['knowledge']['enabled'] = False
        path.write_text(yaml.safe_dump(raw), encoding='utf-8')
        return request(messages, model)
    assert analyze(path, '123', request=changed, model=MODEL)['status'] == 'disabled'
    assert not KnowledgeDB(store.path.parent / 'knowledge.db').items('group:123')


def test_glossary_multiple_evidence_and_conflicts_stay_group_local(tmp_path):
    path, store = configured(tmp_path)
    record(store, '跑图时节点出错', mid=1)
    record(store, '跑图调整节点后恢复', mid=2)
    analyze(path, '123', kind='batch', request=request, model=MODEL)
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    assert db.terms('group:123')[0]['status'] == 'active'
    assert not db.terms('group:999')
    result = {'summary': [], 'items': [], 'terms': [{'term': '跑图', 'meaning': '游戏探索地图', 'evidence_ids': [1, 2]}]}
    db.finish('not-a-real-run', 'group:123', result, 0, extraction=False, glossary=True)
    assert all(t['status'] == 'candidate' for t in db.terms('group:123'))


def test_glossary_unrelated_or_identical_evidence_cannot_activate_term(tmp_path):
    path, store = configured(tmp_path)
    record(store, mid=1)
    record(store, mid=2)
    analyze(path, '123', kind='batch', request=request, model=MODEL)
    assert KnowledgeDB(store.path.parent / 'knowledge.db').terms('group:123')[0]['status'] == 'candidate'


def test_file_link_requires_file_evidence_in_same_message(tmp_path):
    path, store = configured(tmp_path)
    record(store, mid=1)
    record(store, mid=2, file={'name': '资料.pdf', 'id': 'fid-1', 'size': 9})
    rows = read_records(store.path, 'group:123')
    with pytest.raises(ValueError):
        validate_result(response([1], files=['fid-1']), rows)
    assert validate_result(response([2], files=['fid-1']), rows)['items'][0]['file_ids'] == ['fid-1']


def test_history_resumes_and_does_not_touch_live_cursor(tmp_path):
    path, store = configured(tmp_path, features=('summary', 'extraction', 'history'))
    for i in range(1, 12):
        record(store, mid=i)
    first = history(path, '123', '2026-10-12', '2026-10-12', max_batches=1, request=request, model=MODEL)
    second = history(path, '123', '2026-10-12', '2026-10-12', max_batches=3, request=request, model=MODEL)
    assert first['messages'] == 5 and first['has_more']
    assert second['messages'] == 6 and not second['has_more']
    with KnowledgeDB(store.path.parent / 'knowledge.db').conn() as conn:
        assert all(r[0].startswith('history:') for r in conn.execute('SELECT kind FROM cursors'))


def test_history_disabled_even_if_other_features_enabled(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    assert history(path, '123', '2026-10-12', '2026-10-12', request=request, model=MODEL)['status'] == 'disabled'
    assert not (store.path.parent / 'knowledge.db').exists()


def test_budget_reservation_before_request_and_atomic_claim(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    assert db.claim('a', 'group:123', 'manual', 900, 1000, 1, 2) is None
    with pytest.raises(RuntimeError):
        db.claim('a', 'group:123', 'manual', 900, 1000, 1, 2)
    with pytest.raises(RuntimeError):
        db.claim('b', 'group:123', 'manual', 200, 1000, 3, 4)
    assert db.claim('c', 'group:999', 'manual', 900, 1000, 1, 2) is None


def test_automatic_activation_skips_old_history_and_processes_new_messages(tmp_path):
    path, store = configured(tmp_path, min_new_messages=1, interval_minutes=1)
    record(store, mid=1)
    assert automatic_tick(path, request=request, model=MODEL) == []
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    with db.conn() as conn:
        conn.execute('UPDATE cursors SET updated_at=?', ((datetime.now(LOCAL_TZ) - timedelta(minutes=2)).isoformat(),))
    record(store, mid=2)
    results = automatic_tick(path, request=request, model=MODEL)
    assert results[0]['input_count'] == 1
    assert results[0]['start_id'] == 2


def test_view_escapes_model_content_and_knowledge_search_is_group_scoped(tmp_path):
    path, store = configured(tmp_path)
    record(store)
    def malicious(*args):
        result = response([1])
        result['items'][0]['summary'] = '<script>window.bad=1</script> password=very-secret-value'
        return result, 40
    analyze(path, '123', kind='batch', request=malicious, model=MODEL)
    text = write_view(store.path.parent).read_text(encoding='utf-8')
    assert '<script>window.bad' not in text
    assert '&lt;script&gt;window.bad' in text
    assert 'very-secret-value' not in text
    assert '节点排错' in command_reply('群知识', {'message_type': 'group', 'group_id': 123}, path)
    assert '尚未开启' in command_reply('群知识', {'message_type': 'group', 'group_id': 999}, path)


def test_files_only_feature_does_not_persist_knowledge_cards(tmp_path, monkeypatch):
    path, store = configured(tmp_path, features=('files',))
    record(store, file={'name': '资料.pdf', 'id': 'fid-1', 'size': 9})
    saved = []
    import qq_onebot_whitelist.knowledge_files as files
    import qq_onebot_whitelist.file_sync as sync
    monkeypatch.setattr(sync, 'fetch_download_url_once', lambda *a, **k: pytest.fail('mock archive owns URL callback'))
    def archive(source, root, **kwargs):
        saved.append(source)
        return {'status': 'saved', 'path': str(root / 'file.pdf'), 'sha256': 'hash', 'size': 9}
    monkeypatch.setattr(files, 'archive_file', archive)
    analyze(path, '123', feature='files', kind='batch', request=lambda *a: (response([1], files=['fid-1']), 50), model=MODEL)
    assert len(saved) == 1
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    assert not db.items('group:123')
    with db.conn() as conn:
        assert conn.execute('SELECT status FROM assets').fetchone()[0] == 'saved'


def test_secondary_feature_closed_during_call_is_not_cached_as_complete(tmp_path):
    path, store = configured(tmp_path)
    record(store, '跑图时节点出错', mid=1)
    record(store, '跑图调整节点后恢复', mid=2)
    def disable_glossary(messages, model):
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        raw['knowledge']['groups']['group:123']['glossary']['enabled'] = False
        path.write_text(yaml.safe_dump(raw), encoding='utf-8')
        return request(messages, model)
    assert analyze(path, '123', kind='batch', request=disable_glossary, model=MODEL)['status'] == 'disabled'
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups']['group:123']['glossary']['enabled'] = True
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    result = analyze(path, '123', kind='batch', request=request, model=MODEL)
    assert result['terms'] and not result.get('cached')


def test_changed_budget_does_not_skip_live_backlog(tmp_path):
    path, store = configured(tmp_path, min_new_messages=1, interval_minutes=1)
    record(store, mid=1)
    automatic_tick(path, request=request, model=MODEL)
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    with db.conn() as conn:
        conn.execute('UPDATE cursors SET updated_at=?', ((datetime.now(LOCAL_TZ) - timedelta(minutes=2)).isoformat(),))
    record(store, mid=2)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups']['group:123']['max_tokens_per_day'] = 70000
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    results = automatic_tick(path, request=request, model=MODEL)
    assert results[0]['start_id'] == 2


def test_bad_group_config_does_not_starve_other_group(tmp_path):
    path, store = configured(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups'] = {'group:999': {'enabled': True, 'match_mode': 'invalid', 'extraction': {'enabled': True}},
                                **raw['knowledge']['groups']}
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    record(store, mid=1)
    results = automatic_tick(path, request=request, model=MODEL)
    assert results[0]['status'] == 'failed'
    assert KnowledgeDB(store.path.parent / 'knowledge.db').cursor('group:123', 'live')[0] == 1


def test_file_failures_retry_independently_and_on_cache_hit(tmp_path, monkeypatch):
    path, store = configured(tmp_path, features=('files',))
    record(store, file={'name': '资料.pdf', 'id': 'fid-1', 'size': 9})
    calls = []
    import qq_onebot_whitelist.knowledge_files as files
    def archive(*a, **kw):
        calls.append(1)
        return {'status': 'failed', 'error': 'TemporaryFailure'}
    monkeypatch.setattr(files, 'archive_file', archive)
    fake = lambda *a: (response([1], files=['fid-1']), 50)
    analyze(path, '123', feature='files', kind='batch', request=fake, model=MODEL)
    assert analyze(path, '123', feature='files', kind='batch', request=fake, model=MODEL)['cached']
    assert len(calls) == 2
    assert retry_files(path, '123')['attempted'] == 1
    assert len(calls) == 3


def test_missing_asset_does_not_display_saved(tmp_path):
    path, store = configured(tmp_path, features=('files',))
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    db.asset({'scope': 'group:123', 'file_id': 'fid', 'message_id': 1, 'file_name': 'gone.pdf'},
             {'status': 'saved', 'path': str(tmp_path / 'does-not-exist'), 'sha256': 'hash', 'size': 9})
    page = write_view(store.path.parent).read_text(encoding='utf-8')
    assert '文件缺失或校验失败' in page
    assert ' · saved · ' not in page


def test_date_summary_is_batched_resumable_and_reports_partial_coverage(tmp_path):
    path, store = configured(tmp_path, features=('summary',), summary_max_batches=1)
    for i in range(1, 8):
        record(store, mid=i)
    first = summarize_range(path, '123', '2026-10-12', '2026-10-12', request=request, model=MODEL)
    assert first['status'] == 'partial' and first['input_count'] == 5
    second = summarize_range(path, '123', '2026-10-12', '2026-10-12', request=request, model=MODEL)
    assert second['status'] == 'completed' and second['input_count'] == 7
    assert len(second['summary']) == 2


def test_summary_schedule_is_disabled_until_plan_is_explicit(tmp_path):
    path, store = configured(tmp_path, features=('summary',))
    record(store)
    assert automatic_tick(path, request=lambda *a: pytest.fail('no enabled plan'), model=MODEL) == []


def test_retry_rotates_past_permanently_failed_files(tmp_path, monkeypatch):
    path, store = configured(tmp_path, features=('files',))
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    for i in range(4):
        db.asset({'scope': 'group:123', 'file_id': f'fid-{i}', 'message_id': i+1, 'file_name': 'data.pdf', 'file_size': 9},
                 {'status': 'failed', 'error': 'Expired'})
    called = []
    import qq_onebot_whitelist.knowledge_files as files
    def fail(source, *args, **kwargs):
        called.append(source['file_id'])
        return {'status': 'failed', 'error': 'Expired'}
    monkeypatch.setattr(files, 'archive_file', fail)
    retry_files(path, '123')
    retry_files(path, '123')
    assert 'fid-3' in called


def test_missing_saved_file_enters_recovery_queue(tmp_path):
    path, store = configured(tmp_path, features=('files',))
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    db.asset({'scope': 'group:123', 'file_id': 'fid', 'message_id': 1, 'file_name': 'data.pdf', 'file_size': 9},
             {'status': 'saved', 'path': str(tmp_path / 'missing'), 'sha256': 'hash', 'size': 9})
    rows = db.pending_assets('group:123')
    assert rows[0]['file_id'] == 'fid' and rows[0]['error'] == 'IntegrityFailure'


def test_policy_excluded_failures_still_rotate_retry_queue(tmp_path,monkeypatch):
    path,store=configured(tmp_path,features=('files',),files={'enabled':True,'allowed_extensions':['.pdf']})
    db=KnowledgeDB(store.path.parent/'knowledge.db')
    for i in range(4):
        db.asset({'scope':'group:123','file_id':f'fid-{i}','message_id':i+1,
                  'file_name':'file.zip' if i<3 else 'file.pdf','file_size':9}, {'status':'failed'})
    calls=[]
    import qq_onebot_whitelist.knowledge_files as files
    monkeypatch.setattr(files,'archive_file',lambda source,*a,**k:(calls.append(source['file_id']) or {'status':'failed'}))
    retry_files(path,'123')
    retry_files(path,'123')
    assert 'fid-3' in calls


def test_bad_file_limits_are_rejected_before_model_or_budget(tmp_path):
    path,store=configured(tmp_path,features=('files',),files={'enabled':True,'max_file_mb':'bad'})
    record(store,file={'name':'data.pdf','id':'fid','size':9})
    with pytest.raises(ValueError):
        analyze(path,'123',feature='files',request=lambda *a:pytest.fail('bad config must not call AI'),model=MODEL)
    assert not (store.path.parent/'knowledge.db').exists()


def test_zero_file_quota_skips_download_without_failing_analysis(tmp_path,monkeypatch):
    path,store=configured(tmp_path,features=('files',),files={'enabled':True,'budget_gb':0})
    record(store,file={'name':'data.pdf','id':'fid','size':9})
    import qq_onebot_whitelist.file_sync as sync
    monkeypatch.setattr(sync,'fetch_download_url_once',lambda *a,**k:pytest.fail('no space, no URL fetch'))
    result=analyze(path,'123',feature='files',kind='batch',request=lambda *a:(response([1],files=['fid']),50),model=MODEL)
    assert result['status']=='completed'
    with KnowledgeDB(store.path.parent/'knowledge.db').conn() as c:
        row=c.execute('SELECT status,error FROM assets').fetchone()
    assert tuple(row)==('skipped','BudgetExceeded')


def test_confirmed_term_cannot_be_overwritten_by_ai(tmp_path):
    path, store = configured(tmp_path)
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    db.set_term('group:123','抽卡','本群指反复生成图片')
    db.finish('missing','group:123',{'terms':[{'term':'抽卡','meaning':'游戏购买随机角色','evidence_ids':[1,2],
              'supporting_contexts':['a','b']}],'items':[],'summary':[]},0,extraction=False,glossary=True)
    term = db.terms('group:123')[0]
    assert term['origin']=='user' and term['meaning']=='本群指反复生成图片'


def test_unresolved_question_cannot_be_marked_high_value(tmp_path):
    path,store=configured(tmp_path)
    record(store)
    r=response([1])
    r['items'][0]['kind']='未解决'
    value=validate_result(r,read_records(store.path,'group:123'))
    assert value['items'][0]['value']=='candidate'
    assert value['items'][0]['evidence_state']=='unresolved'


def test_existing_provider_fallback_is_budgeted_and_cached(tmp_path,monkeypatch):
    path,store=configured(tmp_path)
    record(store)
    fallback=LLMConfig('https://fallback.invalid/v1','test-key','fallback-model')
    monkeypatch.setattr(LLMConfig,'from_env',lambda:MODEL)
    monkeypatch.setattr(LLMConfig,'ds_fallback_from_env_file',lambda:fallback)
    calls=[]
    def fail_primary(messages,model):
        calls.append(model.model)
        if model is MODEL:raise TimeoutError('not logged')
        return request(messages,model)
    result=analyze(path,'123',request=fail_primary)
    assert result['model']=='fallback-model' and calls==['test-model','fallback-model']
    assert analyze(path,'123',request=fail_primary)['cached']
    db=KnowledgeDB(store.path.parent/'knowledge.db')
    with db.conn() as conn:
        statuses=[r[0] for r in conn.execute('SELECT status FROM runs')]
    assert sorted(statuses)==['completed','failed']

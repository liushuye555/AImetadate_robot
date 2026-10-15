from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from qq_onebot_whitelist.knowledge_topics import ensure_schema, record_updates, thread_candidates, threads


SCOPE = 'group:123'
NOW = '2026-10-15T12:00:00+08:00'


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    ensure_schema(db)
    yield db
    db.close()


def message(mid, text='还没有结果', time='2026-10-10T10:00:00+08:00', **extra):
    return dict(id=mid, scope=SCOPE, text=text, time=time, actor_key='user-a', **extra)


def item(mid=1, **extra):
    return dict(title='安装失败', summary='等待测试反馈', evidence_ids=[mid],
                evidence_state='unresolved', **extra)


def write(conn, entry=None, records=None, allowed=None, run_key='run-1'):
    return record_updates(conn, SCOPE, [entry or item()], records or [message(1)],
                          allowed_threads=allowed or [], now=NOW, run_key=run_key)[0]


def test_new_topic_stable_identity_and_replay_idempotence(conn):
    result = write(conn)
    assert result['inserted']
    assert not write(conn, run_key='retry-run')['inserted']
    assert len(threads(conn)) == 1
    assert len(threads(conn)[0]['events']) == 1
    assert threads(conn)[0]['status'] == 'open'
    other = sqlite3.connect(':memory:')
    ensure_schema(other)
    assert write(other)['thread_id'] == result['thread_id']
    other.close()


def test_same_batch_duplicates_and_event_history_accumulate(conn):
    first = write(conn)
    allowed = thread_candidates(conn, SCOPE)
    update = item(2, thread_id=first['thread_id'], status='in_progress', link_reason='原提问者提供安装日志',
                  known='日志确认依赖缺失', missing=['安装后反馈'])
    results = record_updates(conn, SCOPE, [update, update], [message(2)], allowed_threads=allowed,
                             now=NOW, run_key='run-2')
    assert [row['inserted'] for row in results] == [True, False]
    topic = threads(conn, SCOPE)[0]
    assert topic['evidence_ids'] == [1, 2]
    assert len(topic['events']) == 2
    assert topic['events'][-1]['link_reason'] == update['link_reason']


def test_replay_cannot_replace_or_duplicate_event_with_changed_prose(conn):
    result = write(conn, item(item_key='stable-item', known='首次证据'))
    changed = item(item_key='stable-item', known='重试改写的内容', status='in_progress')
    replay = write(conn, changed, run_key='retry')
    topic = threads(conn)[0]
    assert replay['event_id'] == result['event_id']
    assert replay['status'] == 'open'
    assert not replay['inserted']
    assert topic['known'] == '首次证据'
    assert len(topic['events']) == 1


@pytest.mark.parametrize('case', ['unknown', 'not_shown', 'cross_group', 'forged_scope', 'no_reason'])
def test_untrusted_associations_rejected_atomically(conn, case):
    first = write(conn)
    allowed = thread_candidates(conn, SCOPE)
    target = first['thread_id']
    reason = '同一位成员继续反馈'
    if case == 'unknown':
        target = 'topic_missing'
        allowed = [dict(id=target, scope=SCOPE)]
    elif case == 'not_shown':
        allowed = []
    elif case in ('cross_group', 'forged_scope'):
        foreign = dict(scope='group:999', id=8, text='其他群问题', time=NOW)
        target = record_updates(conn, 'group:999', [item(8)], [foreign], allowed_threads=[],
                                now=NOW, run_key='foreign')[0]['thread_id']
        allowed = [dict(id=target, scope=SCOPE if case == 'forged_scope' else 'group:999')]
    else:
        reason = ''
    before = threads(conn)
    entries = [item(2), item(3, thread_id=target, link_reason=reason)]
    with pytest.raises(ValueError):
        record_updates(conn, SCOPE, entries, [message(2), message(3)], allowed_threads=allowed,
                       now=NOW, run_key='invalid')
    assert threads(conn) == before


@pytest.mark.parametrize('state,quote,context_only', [
    ('reported', '更换依赖后成功启动', False),
    ('verified', '', False),
    ('verified', '模型编出来的成功反馈', False),
    ('verified', '更换依赖后成功启动', True),
])
def test_unsupported_resolution_is_not_promoted(conn, state, quote, context_only):
    entry = dict(title='排错', summary='声称已解决', evidence_ids=[1, 2], status='resolved',
                 value='high', evidence_state=state,
                 resolution_evidence=[dict(message_id=1, quote=quote)])
    write(conn, entry, [message(1, '更换依赖后成功启动', context_only=context_only), message(2)])
    topic = threads(conn)[0]
    assert topic['status'] == 'in_progress'
    assert topic['value'] == 'candidate'
    event = topic['events'][0]
    assert event['requested_status'] == 'resolved'
    assert event['status_reason']
    assert event['value'] == 'candidate'
    assert event['evidence_state'] == 'reported'


def test_pre_normalized_resolution_keeps_original_requested_status_for_audit(conn):
    entry = dict(title='排错', summary='只有尝试计划', evidence_ids=[1], status='in_progress',
                 requested_status='resolved', value='candidate', evidence_state='reported',
                 resolution_evidence=[])
    write(conn, entry, [message(1, '准备试试，还没有测试结果')])
    topic = threads(conn)[0]
    assert topic['status'] == 'in_progress'
    assert topic['value'] == 'candidate'
    assert topic['events'][0]['requested_status'] == 'resolved'
    assert topic['events'][0]['status_reason'] == 'resolved_requires_verified_current_source_quote'


def test_unresolved_cannot_be_high_value_resolved_even_via_direct_module_call(conn):
    entry = item(status='resolved', value='high')
    write(conn, entry)
    topic = threads(conn)[0]
    assert topic['status'] == 'open'
    assert topic['value'] == 'candidate'
    assert topic['events'][0]['requested_status'] == 'resolved'


def test_verified_resolution_requires_real_current_quote_and_records_attribution(conn):
    entry = dict(title='排错', summary='换依赖解决', evidence_ids=[1], status='resolved',
                 value='high', evidence_state='verified',
                 resolution_evidence=[dict(message_id=1, quote='更换依赖后成功启动')])
    write(conn, entry, [message(1, '我已经更换依赖后成功启动，目前正常')])
    topic = threads(conn)[0]
    assert topic['status'] == 'resolved'
    assert topic['value'] == 'high'
    assert topic['events'][0]['evidence_state'] == 'verified'
    assert topic['events'][0]['resolution_evidence'] == entry['resolution_evidence']
    assert topic['events'][0]['sources'][0]['actor_key'] == 'user-a'


def test_late_history_does_not_replace_newer_state_or_snapshots(conn):
    entry = item(status='in_progress', known='新版已部署', missing='等待实测')
    first = write(conn, entry, [message(1, time='2026-10-14T10:00:00+08:00')])
    old = item(90, thread_id=first['thread_id'], link_reason='回填同一问题更早的测试反馈',
               status='resolved', known='旧版测试成功', missing='',
               resolution_evidence=[dict(message_id=90, quote='更换依赖后成功启动')])
    old['evidence_state'] = 'verified'
    write(conn, old, [message(90, '更换依赖后成功启动')], thread_candidates(conn, SCOPE), 'historical')
    topic = threads(conn)[0]
    assert topic['status'] == 'in_progress'
    assert topic['known'] == '新版已部署'
    assert topic['missing'] == '等待实测'
    assert topic['evidence_ids'] == [1, 90]
    assert len(topic['events']) == 2
    assert topic['events'][0]['status'] == 'resolved'


def test_newer_dispute_reopens_resolved_and_unknown_time_cannot_replace_it(conn):
    first = write(conn)
    allowed = thread_candidates(conn, SCOPE)
    feedback = item(2, thread_id=first['thread_id'], link_reason='原问题后续实测', status='resolved',
                    resolution_evidence=[dict(message_id=2, quote='实测成功')])
    feedback['evidence_state'] = 'verified'
    write(conn, feedback, [message(2, '实测成功', '2026-10-11T10:00:00+08:00')], allowed)
    dispute = item(3, thread_id=first['thread_id'], link_reason='同问题复现失败', status='disputed')
    dispute['evidence_state'] = 'disputed'
    write(conn, dispute, [message(3, '还是失败', '2026-10-12T10:00:00+08:00')], allowed)
    unknown = item(99, thread_id=first['thread_id'], link_reason='时间未知的旧记录', status='open')
    write(conn, unknown, [message(99, time=None)], allowed)
    assert threads(conn)[0]['status'] == 'disputed'
    assert len(threads(conn)[0]['events']) == 4


def test_joins_caller_transaction_and_schema_does_not_commit(conn):
    conn.execute('BEGIN')
    ensure_schema(conn)
    write(conn)
    assert conn.in_transaction
    conn.rollback()
    assert threads(conn) == []


def test_standalone_write_leaves_commit_owned_by_caller(conn):
    assert not conn.in_transaction
    write(conn)
    assert conn.in_transaction
    conn.rollback()
    assert threads(conn) == []


def test_concurrent_followups_preserve_all_events_and_newest_source_state(tmp_path):
    path = tmp_path / 'topics.db'
    with sqlite3.connect(path) as db:
        ensure_schema(db)
        first = write(db)
        allowed = thread_candidates(db, SCOPE)
    barrier = Barrier(2)

    def followup(mid, status, when):
        entry = item(mid, thread_id=first['thread_id'], link_reason='同一问题的独立后续反馈',
                     status=status, resolution_evidence=[dict(message_id=mid, quote='实际运行成功')])
        entry['evidence_state'] = 'verified' if status == 'resolved' else 'reported'
        with sqlite3.connect(path, timeout=15) as db:
            barrier.wait(timeout=10)
            write(db, entry, [message(mid, '实际运行成功', when)], allowed, 'run-' + str(mid))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(followup, 2, 'resolved', '2026-10-12T10:00:00+08:00'),
                   pool.submit(followup, 3, 'in_progress', '2026-10-11T10:00:00+08:00')]
        for result in results:
            result.result(timeout=20)
    with sqlite3.connect(path) as db:
        topic = threads(db)[0]
    assert topic['status'] == 'resolved'
    assert topic['evidence_ids'] == [1, 2, 3]
    assert len(topic['events']) == 3


def test_group_local_reads_bounded_limits_and_evidence_validation(conn):
    write(conn)
    assert thread_candidates(conn, 'group:999') == []
    assert threads(conn, 'group:999') == []
    assert thread_candidates(conn, SCOPE, -1) == []
    assert threads(conn, limit=0) == []
    with pytest.raises(ValueError):
        thread_candidates(conn, SCOPE, '100 OR 1=1')
    with pytest.raises(ValueError):
        write(conn, records=[dict(message(1), scope='group:999')])
    with pytest.raises(ValueError):
        write(conn, item(100))
    with pytest.raises(ValueError):
        write(conn, records=[message(1, context_only=True)])


@pytest.mark.parametrize('category', ['knowledge', 'question', 'resource', 'transient'])
def test_category_is_stored_in_topic_events_and_candidates(conn, category):
    write(conn, item(category=category))
    topic = threads(conn)[0]
    assert topic['category'] == category
    assert topic['events'][0]['category'] == category
    assert thread_candidates(conn, SCOPE)[0]['category'] == category


def test_category_defaults_to_question_for_unresolved_evidence(conn):
    write(conn)
    assert threads(conn)[0]['category'] == 'question'


def test_old_or_unknown_feedback_cannot_replace_latest_category_or_resource(conn):
    resource = dict(name='部署工具', purpose='安装依赖', feedback='尚未实测',
                    url='https://example.invalid/tool', status='unverified')
    first = write(conn, item(category='resource', resource=resource, value='high'),
                  [message(1, time='2026-10-14T10:00:00+08:00')])
    allowed = thread_candidates(conn, SCOPE)
    for mid, when in [(90, '2026-10-10T10:00:00+08:00'), (99, None)]:
        old = item(mid, category='transient', resource={'name': '旧反馈应忽略的资源'},
                   thread_id=first['thread_id'], link_reason='回填同一话题早期报告')
        write(conn, old, [message(mid, time=when)], allowed)
    topic = threads(conn)[0]
    assert topic['category'] == 'resource'
    assert topic['resource'] == resource
    assert topic['value'] == 'high'
    assert topic['evidence_ids'] == [1, 90, 99]
    assert len(topic['events']) == 3
    assert sorted(event['category'] for event in topic['events']) == ['resource', 'transient', 'transient']
    update = item(100, category='transient', thread_id=first['thread_id'],
                  link_reason='后续报告明确该信息仅为临时服务状态')
    write(conn, update, [message(100, time='2026-10-15T10:00:00+08:00')], allowed)
    assert threads(conn)[0]['category'] == 'transient'
    assert threads(conn)[0]['resource'] == {}
    assert threads(conn)[0]['value'] == 'candidate'


def test_newer_resource_replaces_resource_metadata(conn):
    first = write(conn, item(category='resource', resource={'name': '旧地址'}))
    update = item(2, category='resource', resource={'name': '新地址', 'feedback': '仍未验证'},
                  thread_id=first['thread_id'], link_reason='原发布者提供新的资源位置')
    write(conn, update, [message(2, time='2026-10-11T10:00:00+08:00')], thread_candidates(conn, SCOPE))
    topic = threads(conn)[0]
    assert topic['resource'] == {'name': '新地址', 'feedback': '仍未验证', 'status': 'unverified'}
    assert topic['events'][0]['resource']['name'] == '旧地址'


def test_persisted_transient_category_survives_without_any_items_window(tmp_path):
    path = tmp_path / 'standalone-topics.db'
    with sqlite3.connect(path) as db:
        ensure_schema(db)
        write(db, item(category='transient', value='high'))
        # The topic read path must work even when there are no knowledge cards.
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='items'").fetchone()
    with sqlite3.connect(path) as db:
        ensure_schema(db)
        assert threads(db)[0]['category'] == 'transient'
        assert threads(db)[0]['value'] == 'high'
        assert thread_candidates(db, SCOPE)[0]['category'] == 'transient'
        assert thread_candidates(db, SCOPE)[0]['value'] == 'high'


def test_schema_upgrades_legacy_tables_without_committing_caller_work():
    with sqlite3.connect(':memory:') as db:
        db.execute('''CREATE TABLE knowledge_threads (
            scope TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL, known TEXT NOT NULL, missing TEXT NOT NULL,
            evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            source_time TEXT, source_stamp REAL, source_message_id INTEGER NOT NULL,
            PRIMARY KEY(scope,id))''')
        db.execute('''CREATE TABLE knowledge_thread_events (
            scope TEXT NOT NULL, id TEXT NOT NULL, thread_id TEXT NOT NULL,
            item_key TEXT NOT NULL, run_key TEXT NOT NULL, created_at TEXT NOT NULL,
            source_time TEXT, source_stamp REAL, source_message_id INTEGER NOT NULL,
            status TEXT NOT NULL, requested_status TEXT NOT NULL, status_reason TEXT NOT NULL,
            title TEXT NOT NULL, summary TEXT NOT NULL, known TEXT, missing TEXT,
            link_reason TEXT NOT NULL, evidence_state TEXT NOT NULL,
            evidence_json TEXT NOT NULL, resolution_json TEXT NOT NULL, sources_json TEXT NOT NULL,
            PRIMARY KEY(scope,id))''')
        db.execute('INSERT INTO knowledge_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (SCOPE, 'legacy', '旧话题', 'open', '', '', '[1]', NOW, NOW, None, None, 1))
        db.commit()
        db.execute('BEGIN')
        ensure_schema(db)
        assert threads(db)[0]['category'] == 'knowledge'
        assert threads(db)[0]['resource'] == {}
        assert threads(db)[0]['value'] == 'candidate'
        db.rollback()
        assert 'category' not in {row[1] for row in db.execute('PRAGMA table_info(knowledge_threads)')}
        assert 'resource_json' not in {row[1] for row in db.execute('PRAGMA table_info(knowledge_thread_events)')}
        assert 'value' not in {row[1] for row in db.execute('PRAGMA table_info(knowledge_threads)')}
        ensure_schema(db)
        # Migration is repeatable and explicit INSERT columns tolerate future additions.
        ensure_schema(db)
        db.execute('ALTER TABLE knowledge_threads ADD COLUMN future_column TEXT')
        db.execute('ALTER TABLE knowledge_thread_events ADD COLUMN future_column TEXT')
        write(db, item(2, category='transient'), [message(2)])
        assert next(row for row in threads(db) if row['id'] != 'legacy')['category'] == 'transient'

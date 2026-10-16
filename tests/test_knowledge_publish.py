import json
import sqlite3

import pytest

from qq_onebot_whitelist.knowledge import write_view
from qq_onebot_whitelist.knowledge_publish import publish_history
from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist import knowledge_organization, knowledge_topics
from qq_onebot_whitelist.store import Store


SCOPE = 'group:123'


def prepared(tmp_path):
    source, target = tmp_path / 'analysis', tmp_path / 'data'
    source.mkdir()
    target.mkdir()
    for directory in (source, target):
        store = Store(directory / 'bot.db')
        store.record_message(scope=SCOPE, user_id='7', text='调整节点后正常了',
                             raw={'message_id': 9, 'time': 1791777600})
    db = KnowledgeDB(source / 'knowledge.db')
    db.claim('history-run', SCOPE, 'history', 100, 10000, 1, 1)
    db.finish('history-run', SCOPE, {
        'summary': [{'text': '调整节点后恢复', 'evidence_ids': [1]}],
        'items': [{'title': '节点排错', 'summary': '调整节点后恢复，版本未知。',
                   'kind': '排错', 'topic': '软件使用', 'value': 'candidate',
                   'evidence_ids': [1], 'file_ids': [], 'category': 'knowledge'}],
        'terms': [{'term': '节点', 'meaning': '本次讨论的处理模块', 'evidence_ids': [1]}],
    }, 80, extraction=True, glossary=True)
    return source, target, db


def test_publish_makes_offline_results_visible_without_enabling_ai(tmp_path):
    source, target, source_db = prepared(tmp_path)
    result = publish_history(source, target, SCOPE)
    assert result['status'] == 'published'
    assert result['message_count'] == 1
    assert result['inserted']['items'] == 1
    page = write_view(target)
    html = page.read_text(encoding='utf-8')
    assert '节点排错' in html and '调整节点后正常了' in html
    assert '原记录不可用' not in html
    assert '本次讨论的处理模块' in (page.parent / 'glossary.html').read_text(encoding='utf-8')
    assert '调整节点后恢复' in (page.parent / 'knowledge-summary.html').read_text(encoding='utf-8')
    assert len(source_db.items()) == 1
    assert not (target / 'config.yaml').exists()


def test_repeated_publication_is_idempotent_and_keeps_runtime_state(tmp_path):
    source, target, source_db = prepared(tmp_path)
    with source_db.conn() as conn:
        conn.execute("INSERT INTO cursors VALUES (?,?,?,?)", (SCOPE, 'batch', 1, 'now'))
        conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ('failed-run', SCOPE, 'history', '2026-10-16', 'failed', 900, 'now', 1, 1, None, 'error'))
    dest = KnowledgeDB(target / 'knowledge.db')
    with dest.conn() as conn:
        conn.execute("INSERT INTO cursors VALUES (?,?,?,?)", (SCOPE, 'batch', 999, 'now'))
    first = publish_history(source, target, SCOPE)
    second = publish_history(source, target, SCOPE)
    assert first['status'] == 'published' and second['status'] == 'unchanged'
    with dest.conn() as conn:
        assert conn.execute('SELECT count(*) FROM items').fetchone()[0] == 1
        assert conn.execute('SELECT last_id FROM cursors').fetchone()[0] == 999
        assert conn.execute('SELECT key FROM runs').fetchall()[0][0] == 'history-run'
        assert conn.execute('SELECT count(*) FROM knowledge_publications').fetchone()[0] == 1
    assert first['backup'] and (target / first['backup']).exists()


@pytest.mark.parametrize('change', ["text='不同原文'", "scope='group:456'", "raw_json='{}'", "message_key='different'"])
def test_different_live_source_message_refuses_publication(tmp_path, change):
    source, target, _ = prepared(tmp_path)
    with sqlite3.connect(target / 'bot.db') as conn:
        conn.execute('UPDATE messages SET ' + change)
    with pytest.raises(ValueError, match='原消息'):
        publish_history(source, target, SCOPE)
    assert not (target / 'knowledge.db').exists()


def test_out_of_snapshot_evidence_is_refused(tmp_path):
    source, target, db = prepared(tmp_path)
    with db.conn() as conn:
        conn.execute('UPDATE items SET evidence_json=?', (json.dumps([999]),))
    with pytest.raises(ValueError, match='证据'):
        publish_history(source, target, SCOPE)
    assert not (target / 'knowledge.db').exists()


@pytest.mark.parametrize('table,column,value', [
    ('item_quality', 'quality_json', {'result_quote': {'message_id': 999, 'quote': '不同群'}}),
    ('item_organization', 'organization_json', {'progress_evidence': {'message_id': 999}}),
    ('item_organization', 'organization_json', {'subject': {'evidence': [{'message_id': 999}]}}),
])
def test_nested_annotation_evidence_must_also_be_in_snapshot(tmp_path, table, column, value):
    source, target, db = prepared(tmp_path)
    with db.conn() as conn:
        key = conn.execute('SELECT key FROM items').fetchone()[0]
        if table == 'item_organization':
            conn.execute('INSERT OR REPLACE INTO item_organization VALUES (?,?)', (key, json.dumps(value)))
        else:
            conn.execute('UPDATE ' + table + ' SET ' + column + '=?', (json.dumps(value),))
    with pytest.raises(ValueError, match='证据'):
        publish_history(source, target, SCOPE)
    assert not (target / 'knowledge.db').exists()


def test_conflicting_existing_content_rolls_back_every_table(tmp_path):
    source, target, _ = prepared(tmp_path)
    publish_history(source, target, SCOPE)
    dest = KnowledgeDB(target / 'knowledge.db')
    with dest.conn() as conn:
        conn.execute("UPDATE items SET body='用户修改的结论'")
        conn.execute('DELETE FROM runs')
    with pytest.raises(ValueError, match='冲突'):
        publish_history(source, target, SCOPE)
    with dest.conn() as conn:
        assert conn.execute('SELECT body FROM items').fetchone()[0] == '用户修改的结论'
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_source_is_required_and_other_groups_are_not_published(tmp_path):
    source, target, db = prepared(tmp_path)
    with db.conn() as conn:
        conn.execute("INSERT INTO items SELECT 'other', 'group:456', created_at, title, body, kind, topic, value, evidence_json, files_json, evidence_state FROM items")
    publish_history(source, target, SCOPE)
    assert not KnowledgeDB(target / 'knowledge.db').items('group:456')
    with pytest.raises(ValueError):
        publish_history(target, target, SCOPE)
    with pytest.raises(ValueError):
        publish_history(tmp_path / 'missing', target, SCOPE)


def test_topic_history_organization_and_term_annotations_survive_publication(tmp_path):
    source, target, db = prepared(tmp_path)
    item = db.items()[0]
    with db.conn() as conn:
        knowledge_topics.record_updates(conn, SCOPE, [{**item, 'summary': item['body'],
            'evidence_ids': [1], 'status': 'open', 'evidence_state': 'reported'}],
            [{'id': 1, 'scope': SCOPE, 'text': '调整节点后正常了', 'time': '2026-10-12T12:00:00+08:00'}],
            allowed_threads=[], now='2026-10-16T12:00:00+08:00', run_key='history-run')
        conn.execute('INSERT OR REPLACE INTO item_organization VALUES (?,?)',
                     (item['key'], json.dumps({'topics': ['development'], 'retention': 'detailed'})))
    topic = db.threads()[0]
    knowledge_organization.set_archive(db, SCOPE, 'topic', topic['id'], 'active', reason='人工保留')
    publish_history(source, target, SCOPE)
    dest = KnowledgeDB(target / 'knowledge.db')
    assert dest.threads() == db.threads()
    assert dest.items()[0]['organization'] == db.items()[0]['organization']
    with dest.conn() as conn, db.conn() as original:
        for table in ('term_annotations', 'knowledge_archives'):
            assert [tuple(r) for r in conn.execute('SELECT * FROM ' + table)] == [
                tuple(r) for r in original.execute('SELECT * FROM ' + table)]
    html = write_view(target).read_text(encoding='utf-8')
    assert html.count('<article ') == 1
    assert '调整节点后正常了' in html

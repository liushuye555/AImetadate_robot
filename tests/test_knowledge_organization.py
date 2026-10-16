import sqlite3

import pytest

from qq_onebot_whitelist import knowledge_organization as org
from qq_onebot_whitelist.knowledge import validate_result
from qq_onebot_whitelist.knowledge_store import KnowledgeDB


def item(**updates):
    row = {'title': '使用反馈', 'summary': '我的已经封了，所指对象未知', 'kind': '讨论',
           'topic': 'AI', 'value': 'high', 'evidence_ids': [1], 'file_ids': [],
           'evidence_state': 'reported', 'quality': {'basis': 'personal_opinion'}}
    row.update(updates)
    return row


def test_topics_are_bounded_independent_metadata():
    row = item(organization={'topics': ['accounts', 'accounts', 'bad', {}, 'billing', 'model_usage', 'other']})
    assert org.prepare_organization(row, [])['topics'] == ['accounts', 'billing', 'model_usage']
    assert org.prepare_organization(item(), [])['topics'] == ['other']


@pytest.mark.parametrize('record,quote', [
    ({'id': 1, 'text': '我的已经封了', 'context_only': True}, '我的已经封了'),
    ({'id': 1, 'text': '我的已经封了'}, 'GPT账号被封'),
    ({'id': 2, 'text': '我的已经封了'}, '我的已经封了'),
])
def test_only_exact_current_item_evidence_can_advance_progress(record, quote):
    row = item(organization={'progress_kind': 'new_information', 'progress_evidence': {'message_id': 1, 'quote': quote}})
    assert org.prepare_organization(row, [record])['progress_kind'] == 'unknown'


def test_exact_new_progress_and_subject_are_preserved():
    row = item(organization={'progress_kind': 'new_information',
        'progress_evidence': {'message_id': 1, 'quote': 'GPT恢复了'},
        'subject': {'name': 'GPT', 'evidence': [{'message_id': 1, 'quote': 'GPT恢复了'}]}})
    result = org.prepare_organization(row, [{'id': 1, 'text': '重启后GPT恢复了'}])
    assert result['progress_kind'] == 'new_information'
    assert result['subject']['name'] == 'GPT'
    row['organization']['subject']['name'] = '工具A'
    result = org.prepare_organization(row, [{'id': 1, 'text': '重启后GPT恢复了'}])
    assert result['subject'] == {'name': '', 'ambiguous': True, 'evidence': [{'message_id': 1, 'quote': 'GPT恢复了'}]}


def test_progress_clock_uses_the_validated_quote_message_time():
    row = item(evidence_ids=[1, 2], organization={'progress_kind': 'new_information',
               'progress_evidence': {'message_id': 1, 'quote': '恢复了'}})
    result = org.prepare_organization(row, [
        {'id': 1, 'text': '恢复了', 'time': '2026-10-01T08:00:00+08:00'},
        {'id': 2, 'text': '有进展吗', 'time': '2026-10-15T08:00:00+08:00'}])
    assert result['progress_time'] == result['first_source_time'] == '2026-10-01T00:00:00+00:00'


def test_subject_can_be_grounded_in_a_collected_file_preview():
    row = item(organization={'subject': {'name': 'Python', 'ambiguous': False,
        'evidence': [{'message_id': 1, 'quote': 'Python 3.12'}]}})
    record = {'id': 1, 'text': '附件教程', 'files': [{'preview': {'text': '环境：Python 3.12'}}]}
    result = org.prepare_organization(row, [record])
    assert result['subject']['name'] == 'Python' and not result['subject']['ambiguous']
    record['context_only'] = True
    row['organization']['progress_kind'] = 'new_information'
    row['organization']['progress_evidence'] = {'message_id': 1, 'quote': 'Python 3.12'}
    assert org.prepare_organization(row, [record])['progress_kind'] == 'unknown'


def test_ambiguous_claim_stays_a_question_across_revalidation():
    row = item(organization={'subject': {'ambiguous': True}})
    records = [{'id': 1, 'text': '我的已经封了', 'files': [], 'links': []}]
    first = validate_result({'items': [row]}, records)['items'][0]
    second = validate_result({'items': [first]}, records)['items'][0]
    assert first['title'] == second['title'] == '群友说法：对象待确认：使用反馈'
    assert first['missing'] == second['missing']
    assert second['category'] == 'question' and second['value'] == 'candidate'
    assert second['evidence_state'] == 'reported'


@pytest.mark.parametrize('subject', [None, {}, {'name': '', 'ambiguous': False},
                                     {'name': 'GPT', 'ambiguous': False}])
def test_missing_or_unsupported_subject_cannot_silently_become_confirmed(subject):
    raw = {'topics': ['accounts']}
    if subject is not None:
        raw['subject'] = subject
    result = org.prepare_organization(item(organization=raw), [{'id': 1, 'text': '我的已经封了'}])
    assert result['subject']['ambiguous'] and result['subject']['name'] == ''


def test_organization_survives_storage_and_legacy_reads(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    with db.conn() as conn:
        org.save_organization(conn, 'one', {'organization': {'topics': ['accounts']}})
        assert org.decorate_organization(conn, {'key': 'one'})['organization']['topics'] == ['accounts']
    conn = sqlite3.connect(':memory:')
    assert org.decorate_organization(conn, {'key': 'legacy'}) == {'key': 'legacy'}
    assert org.archive_overrides(conn) == {}


def test_archive_is_scoped_reversible_and_preserves_content(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    with db.conn() as conn:
        conn.execute("INSERT INTO items(key,scope,created_at,title,body,evidence_json,files_json) VALUES ('one','group:1','now','title','body','[]','[]')")
    with pytest.raises(ValueError, match='不属于本群'):
        org.set_archive(db, 'group:2', 'item', 'one', 'archived')
    org.set_archive(db, 'group:1', 'item', 'one', 'archived')
    assert len(db.items('group:1')) == 1
    assert db.context_items('group:1') == []
    org.set_archive(db, 'group:1', 'item', 'one', 'active')
    assert len(db.context_items('group:1')) == 1
    org.set_archive(db, 'group:1', 'item', 'one', 'auto')
    with db.conn() as conn:
        assert org.archive_overrides(conn) == {}


def test_tracked_item_archive_requires_the_complete_topic(tmp_path):
    from test_knowledge_archive_context import _add_topic, _add_item
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    _add_topic(db, 'group:1', 'topic-one')
    _add_item(db, 'group:1', 'item-topic-one')
    with pytest.raises(ValueError, match='--topic-id topic-one'):
        org.set_archive(db, 'group:1', 'item', 'item-topic-one', 'archived')
    org.set_archive(db, 'group:1', 'topic', 'topic-one', 'archived')
    assert db.context_items('group:1') == []
    assert db.thread_candidates('group:1') == []

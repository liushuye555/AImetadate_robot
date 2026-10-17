import json
import sqlite3

import pytest

from qq_onebot_whitelist.knowledge_tags import prepare_topic_tags, topic_tags_for
from qq_onebot_whitelist import knowledge_subject_review as review


def test_generic_topic_is_independent_of_unknown_vendor_and_exact_spelling():
    record = {'id': 1, 'text': '谁有渠道可以开虚拟visa卡'}
    raw = [{'name': '虚拟卡', 'evidence': [{'message_id': 1, 'quote': record['text']}]}]
    tags = prepare_topic_tags(raw, {'evidence_ids': [1]}, [record])
    assert topic_tags_for({'organization': {'subject': {'ambiguous': True}, 'topic_tags': tags}}) == ['虚拟卡']
    assert tags[0]['origin'] == 'ai'


@pytest.mark.parametrize('mid,quote', [(2, '虚拟visa卡'), (1, '虚拟Visa卡'), (True, '虚拟visa卡')])
def test_topic_cannot_use_foreign_ids_or_invented_quote(mid, quote):
    raw = [{'name': '虚拟卡', 'evidence': [{'message_id': mid, 'quote': quote}]}]
    assert prepare_topic_tags(raw, {'evidence_ids': [1]}, [{'id': 1, 'text': '虚拟visa卡'}]) == []


def test_topics_can_extend_beyond_a_fixed_dictionary_without_adding_facts():
    raw = [{'name': '内存容量对比', 'origin': 'user', 'evidence': [{'message_id': 1, 'quote': '32G和64G用起来差多少'}]}]
    result = prepare_topic_tags(raw, {'evidence_ids': [1]}, [{'id': 1, 'text': '32G和64G用起来差多少'}])
    assert result[0]['name'] == '内存容量对比' and result[0]['origin'] == 'ai'


def test_existing_attachment_name_can_support_topic_without_claiming_file_content():
    record = {'id': 1, 'text': '', 'files': [{'file_name': '本地知识库搭建.md'}]}
    raw = [{'name': '本地知识库', 'evidence': [{'message_id': 1, 'quote': '本地知识库搭建.md'}]}]
    result = prepare_topic_tags(raw, {'evidence_ids': [1]}, [record])
    assert result[0]['evidence'][0]['source_field'] == 'file_name'
    assert prepare_topic_tags(raw, {'evidence_ids': [2]}, [record]) == []


def test_targeted_review_cannot_escape_group_scope(tmp_path, monkeypatch):
    from test_knowledge_subject_review import prepared, MODEL, SCOPE
    prepared(tmp_path, monkeypatch, count=2)
    with pytest.raises(ValueError, match='不属于本群'):
        review.review_subjects('unused', SCOPE, with_topics=True, model=MODEL, only_keys=['foreign-key'])


def test_rejected_entity_cannot_mark_empty_topic_classification_complete():
    from qq_onebot_whitelist.knowledge_organization import prepare_organization
    item = {'evidence_ids': [1], 'organization': {'topic_tags': [], 'subjects': [
        {'name': 'GPT', 'evidence': [{'message_id': 1, 'quote': '这个不行'}]}]}}
    result = prepare_organization(item, [{'id': 1, 'text': '这个不行'}])
    assert result['subjects'] == [] and result['topic_tags'] == []
    assert result['tags_complete'] is False


def test_migration_rechecks_old_completed_empty_subjects_and_saves_topics(tmp_path, monkeypatch):
    from test_knowledge_subject_review import prepared, annotations, MODEL, SCOPE
    _, db = prepared(tmp_path, monkeypatch, count=1)
    with db.conn() as conn:
        conn.execute('UPDATE item_organization SET organization_json=?', (json.dumps({
            'subjects': [], 'subjects_version': 1, 'subjects_complete': True, 'subject': {'ambiguous': True}}),))
    with sqlite3.connect(tmp_path / 'bot.db') as conn:
        conn.execute('UPDATE messages SET text=? WHERE id=1', ('谁有渠道可以开虚拟visa卡',))
    def request(messages, model, **kwargs):
        assert kwargs['max_tokens'] == 4000
        task = json.loads(messages[1]['content'])
        assert 'internet_background' in task and '虚拟卡' in task['preferred_tags']
        return {'decisions': [{'key': 'item-0', 'subjects': [], 'topic_tags': [{'name': '虚拟卡',
            'evidence': [{'message_id': 1, 'quote': '虚拟visa卡'}]}]}]}, 90
    result = review.review_subjects('unused', SCOPE, with_topics=True, request=request, model=MODEL)
    assert result['processed'] == 1 and result['status'] == 'completed'
    org = annotations(db)['item-0']
    assert org['subjects'] == [] and org['subject']['ambiguous'] is True
    assert org['topic_tags'][0]['name'] == '虚拟卡' and org['tags_complete'] is True
    result = review.review_subjects('unused', SCOPE, with_topics=True,
        request=lambda *_a, **_kw: pytest.fail('unnecessary AI call'), model=MODEL)
    assert result['status'] == 'unchanged'


def test_topic_review_rejects_an_unsupported_batch_without_partial_writes(tmp_path, monkeypatch):
    from test_knowledge_subject_review import prepared, annotations, MODEL, SCOPE
    _, db = prepared(tmp_path, monkeypatch, count=1)
    before = annotations(db)
    def request(*_a, **_kw):
        return {'decisions': [{'key': 'item-0', 'subjects': [], 'topic_tags': [{'name': '虚拟卡',
            'evidence': [{'message_id': 99, 'quote': '其他群'}]}]}]}, 10
    result = review.review_subjects('unused', SCOPE, with_topics=True, request=request, model=MODEL)
    assert result['status'] == 'failed' and result['processed'] == 0
    assert annotations(db) == before


def test_truly_unclassified_requires_reason_and_retains_it(tmp_path, monkeypatch):
    from test_knowledge_subject_review import prepared, annotations, MODEL, SCOPE
    _, db = prepared(tmp_path, monkeypatch, count=1)
    result = review.review_subjects('unused', SCOPE, with_topics=True, model=MODEL,
        request=lambda *_a, **_kw: ({'decisions': [{'key': 'item-0', 'subjects': [], 'topic_tags': [],
                   'unknown_reason': '仅有指代，缺少具体资料主题'}]}, 10))
    assert result['status'] == 'completed'
    assert '缺少' in annotations(db)['item-0']['classification_note']


def test_partial_classification_cannot_be_promoted_by_repeated_cache_hits(tmp_path, monkeypatch):
    from test_knowledge_subject_review import prepared, annotations, MODEL, SCOPE, runs
    _, db = prepared(tmp_path, monkeypatch, count=1, budget=200000)
    calls = []
    def request(*_a, **_kw):
        calls.append(True)
        return {'decisions': [{'key': 'item-0', 'subjects': [], 'classification_incomplete': True,
            'topic_tags': [{'name': '软件排错', 'evidence': [{'message_id': 1, 'quote': '调整节点后正常了'}]}]}]}, 20
    for expected_calls in range(1, 5):
        result = review.review_subjects('unused', SCOPE, with_topics=True, request=request, model=MODEL)
        assert result['status'] == 'partial' and result['remaining'] == 1
        assert len(calls) == expected_calls
        assert annotations(db)['item-0']['tags_complete'] is False
    assert sum(row['tokens'] for row in runs(db)) == 80

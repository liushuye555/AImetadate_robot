import json

import pytest

from qq_onebot_whitelist.knowledge_topic_decisions import apply_decisions, messages_for, needs_decisions
from qq_onebot_whitelist.knowledge_topic_decisions import guard_question_links


SCOPE = 'group:123'
ITEMS = [{'title': 'Same outage', 'summary': 'A later recovery report', 'evidence_ids': [20]}]
THREADS = [{'id': 'old', 'scope': SCOPE, 'title': 'Same outage'}]


def decision(**overrides):
    return {'decisions': [dict(index=0, action='existing', thread_id='old',
                              reason='Same public outage, new recovery report', status='in_progress', **overrides)]}


def test_missing_association_with_candidates_needs_a_real_decision():
    assert needs_decisions(ITEMS, THREADS)
    assert not needs_decisions(ITEMS, [])
    assert needs_decisions([{**ITEMS[0], 'thread_id': 'old', 'link_reason': 'same outage'}], THREADS)
    assert needs_decisions([{**ITEMS[0], 'topic_action': 'existing', 'thread_id': 'old',
                             'link_reason': 'same outage'}], THREADS)
    assert not needs_decisions([{**ITEMS[0], 'topic_action': 'new'}], THREADS)
    with pytest.raises(ValueError, match='决策不完整'):
        apply_decisions({'items': ITEMS}, ITEMS, THREADS, SCOPE)


def test_explicit_followup_preserves_prose_and_associates_allowed_id():
    result = apply_decisions(decision(), ITEMS, THREADS, SCOPE)
    assert result[0]['thread_id'] == 'old' and result[0]['title'] == ITEMS[0]['title']
    assert 'thread_id' not in ITEMS[0]


@pytest.mark.parametrize('target,scope', [('foreign', SCOPE), ('old', 'group:999')])
def test_decisions_cannot_link_outside_the_shown_same_group_snapshot(target, scope):
    value = decision(); value['decisions'][0]['thread_id'] = target
    with pytest.raises(ValueError, match='候选以外'):
        apply_decisions(value, ITEMS, THREADS, scope)


def test_missing_or_repeated_item_decisions_are_rejected():
    value = decision(); value['decisions'] *= 2
    with pytest.raises(ValueError):
        apply_decisions(value, ITEMS * 2, THREADS, SCOPE)


def test_ignore_does_not_create_an_empty_duplicate_topic():
    value = decision(); value['decisions'][0].update(action='ignore', thread_id=None)
    assert apply_decisions(value, ITEMS, THREADS, SCOPE) == []


def test_missing_status_is_conservative_and_does_not_discard_valid_association():
    value = decision(); value['decisions'][0].pop('status')
    result = apply_decisions(value, ITEMS, THREADS, SCOPE)
    assert result[0]['status'] == 'in_progress' and result[0]['thread_id'] == 'old'
    value['decisions'][0].update(action='new', thread_id=None)
    assert apply_decisions(value, ITEMS, THREADS, SCOPE)[0]['status'] == 'open'


def test_decision_task_contains_actual_sources_and_one_index_per_item():
    source = [{'id': 20, 'text': 'The same service is back', 'context_only': False}]
    messages = messages_for(ITEMS, THREADS, source)
    task = json.loads(messages[1]['content'])
    assert task['items'][0]['index'] == 0 and task['messages'] == source
    assert task['task_type'] == 'topic_decisions'


def test_different_members_independent_question_does_not_join_a_tool_introduction():
    item = {**ITEMS[0], 'category': 'question', 'thread_id': 'old', 'status': 'in_progress',
            'link_reason': 'Both mention the same tool'}
    prior = [{**THREADS[0], 'category': 'knowledge', 'evidence_ids': [1]}]
    records = [{'id': 1, 'actor_key': 'alice', 'context_only': True},
               {'id': 20, 'actor_key': 'bob', 'context_only': False, 'quoted_id': None}]
    result = guard_question_links([item], prior, records)[0]
    assert result['topic_action'] == 'new' and 'thread_id' not in result
    assert result['requested_thread_id'] == 'old' and result['status'] == 'open'
    records[1]['quoted_id'] = 1
    assert guard_question_links([item], prior, records)[0]['thread_id'] == 'old'


@pytest.mark.parametrize('prior_category', ['transient', 'question'])
def test_public_service_event_can_have_different_members_without_direct_replies(prior_category):
    item = {**ITEMS[0], 'category': 'transient', 'thread_id': 'old'}
    prior = [{**THREADS[0], 'category': prior_category, 'evidence_ids': [1]}]
    records = [{'id': 1, 'actor_key': 'alice', 'context_only': True},
               {'id': 20, 'actor_key': 'bob', 'context_only': False}]
    assert guard_question_links([item], prior, records)[0]['thread_id'] == 'old'

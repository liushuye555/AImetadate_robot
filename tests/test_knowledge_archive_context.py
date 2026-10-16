from datetime import datetime, timezone

from qq_onebot_whitelist.knowledge_store import KnowledgeDB


class Profile:
    settings = {'lifecycle': {'brief_days': 3, 'detailed_days': 14,
                              'transient_days': 3, 'resource_days': 30}}

    def __init__(self, enabled=True):
        self.enabled = enabled

    def option_enabled(self, section, key):
        return self.enabled and section == 'lifecycle' and key == 'enabled'


def _add_topic(db, scope, topic_id, *, when='2020-01-01T00:00:00+00:00',
               category='knowledge', evidence_state='reported', evidence_id=1):
    stamp = datetime.fromisoformat(when).timestamp()
    with db.conn() as conn:
        conn.execute('''INSERT INTO knowledge_threads
            (scope,id,title,status,known,missing,evidence_json,created_at,updated_at,
             source_time,source_stamp,source_message_id,category,resource_json,value)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (scope, topic_id, topic_id, 'open', '', '', f'[{evidence_id}]', when, when,
             when, stamp, evidence_id, category, '{}', 'candidate'))
        conn.execute('''INSERT INTO knowledge_thread_events
            (scope,id,thread_id,item_key,run_key,created_at,source_time,source_stamp,source_message_id,
             status,requested_status,status_reason,title,summary,known,missing,link_reason,evidence_state,
             evidence_json,resolution_json,sources_json,category,resource_json,value)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (scope, 'event-' + topic_id, topic_id, 'item-' + topic_id, 'run', when, when, stamp,
             evidence_id, 'open', 'open', '', topic_id, 'summary', '', '', '', evidence_state,
             f'[{evidence_id}]', '[]', '[]', category, '{}', 'candidate'))


def _add_item(db, scope, key, *, category='knowledge', when='2020-01-01T00:00:00+00:00'):
    with db.conn() as conn:
        conn.execute('''INSERT INTO items(key,scope,created_at,title,body,evidence_json,files_json)
                        VALUES (?,?,?,?,?,?,?)''', (key, scope, when, key, 'body', '[]', '[]'))
        conn.execute('''INSERT INTO item_details(item_key,category,known_text,missing_text,source_time,resource_json)
                        VALUES (?,?,?,?,?,?)''', (key, category, '', '', when, '{}'))


def test_default_disabled_lifecycle_does_not_auto_archive():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db')
        db.lifecycle_profile = None
        _add_topic(db, 'group:1', 'old-question', category='question')
        assert db.archived_context('group:1') == (set(), set())
        assert [row['id'] for row in db.thread_candidates('group:1')] == ['old-question']


def test_manual_archive_excludes_topic_candidate_and_item_context():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db')
        _add_topic(db, 'group:1', 'manual-topic', when='2026-10-15T00:00:00+00:00')
        _add_item(db, 'group:1', 'item-manual-topic', when='2026-10-15T00:00:00+00:00')
        _add_item(db, 'group:1', 'manual-item', when='2026-10-15T00:00:00+00:00')
        _add_item(db, 'group:1', 'other-item', when='2026-10-15T00:00:00+00:00')
        with db.conn() as conn:
            conn.execute("INSERT INTO knowledge_archives VALUES ('group:1','topic','manual-topic','archived','manual','now')")
            conn.execute("INSERT INTO knowledge_archives VALUES ('group:1','item','manual-item','archived','manual','now')")
        db.lifecycle_profile = None
        assert db.thread_candidates('group:1') == []
        assert [item['key'] for item in db.context_items('group:1')] == ['other-item']


def test_expired_question_is_excluded_before_candidate_limit_and_old_active_is_kept():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db', lifecycle_profile=Profile())
        _add_topic(db, 'group:1', 'new-expired', when='2026-10-01T00:00:00+00:00', category='question', evidence_state='unresolved')
        _add_topic(db, 'group:1', 'old-active', when='2026-01-01T00:00:00+00:00', category='knowledge')
        candidates = db.thread_candidates('group:1', limit=1)
        assert [row['id'] for row in candidates] == ['old-active']


def test_latest_event_category_controls_unresolved_followup_classification():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db', lifecycle_profile=Profile())
        _add_topic(db, 'group:1', 'valid-knowledge', category='knowledge', evidence_state='unresolved')
        _add_topic(db, 'group:1', 'unclassified-unresolved', category='knowledge', evidence_state='unresolved', evidence_id=2)
        with db.conn() as conn:
            conn.execute("UPDATE knowledge_thread_events SET category='' WHERE thread_id='unclassified-unresolved'")
        archived, _ = db.archived_context('group:1')
        assert 'unclassified-unresolved' in archived
        assert 'valid-knowledge' not in archived


def test_auto_archived_topic_can_be_candidate_on_direct_reply():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db', lifecycle_profile=Profile(),
                         context_quote_ids={42})
        _add_topic(db, 'group:1', 'old-question', category='question', evidence_state='unresolved', evidence_id=42)
        candidates = db.thread_candidates('group:1')
        assert len(candidates) == 1
        assert candidates[0]['id'] == 'old-question'
        assert candidates[0]['archived'] is True


def test_archive_and_candidates_are_group_local():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db')
        _add_topic(db, 'group:1', 'one')
        _add_topic(db, 'group:2', 'two')
        with db.conn() as conn:
            conn.execute("INSERT INTO knowledge_archives VALUES ('group:2','topic','two','archived','manual','now')")
        assert [row['id'] for row in db.thread_candidates('group:1')] == ['one']
        assert db.thread_candidates('group:2') == []


def test_direct_reply_matches_earliest_evidence_beyond_prompt_limit(tmp_path):
    import json
    db = KnowledgeDB(tmp_path / 'knowledge.db', lifecycle_profile=Profile(), context_quote_ids={1})
    _add_topic(db, 'group:1', 'long-question', category='question', evidence_state='unresolved')
    with db.conn() as conn:
        conn.execute('UPDATE knowledge_threads SET evidence_json=? WHERE id=?',
                     (json.dumps(list(range(1, 45))), 'long-question'))
    candidate = db.thread_candidates('group:1')[0]
    assert candidate['id'] == 'long-question' and candidate['archived']
    assert 1 in candidate['evidence_ids']


def test_directly_quoted_archive_is_prioritized_over_recent_candidate_limit(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db', lifecycle_profile=Profile(), context_quote_ids={1})
    _add_topic(db, 'group:1', 'old-question', category='question', evidence_state='unresolved')
    for number in range(15):
        _add_topic(db, 'group:1', f'recent-{number}', when='2026-10-15T00:00:00+00:00', evidence_id=number+10)
    candidates = db.thread_candidates('group:1')
    assert len(candidates) == 12
    assert candidates[0]['id'] == 'old-question' and candidates[0]['archived']


def test_threads_limit_none_reads_complete_history_without_default_cap():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as temp:
        db = KnowledgeDB(Path(temp) / 'knowledge.db')
        for number in range(205):
            _add_topic(db, 'group:1', f'topic-{number}', when='2026-01-01T00:00:00+00:00', evidence_id=number + 1)
        assert len(db.threads('group:1')) == 200
        assert len(db.threads('group:1', limit=None)) == 205

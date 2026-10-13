import pytest
from contextlib import contextmanager

from qq_onebot_whitelist.store import Store


def _image(store: Store, scope: str) -> int:
    store.record_image(
        scope=scope,
        user_id='user',
        result={'url': 'https://example.test/image.png'},
        raw={},
    )
    with store._conn() as conn:
        return int(conn.execute('SELECT MAX(id) FROM images WHERE scope = ?', (scope,)).fetchone()[0])


def _message(store: Store, scope: str, key: str) -> int:
    store.record_message(scope=scope, user_id='user', text='context', raw={'message_id': key})
    return store.message_row_id(scope, {'message_id': key})


def test_image_discussion_round_trip_and_redaction(tmp_path):
    store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')
    evidence_id = _message(store, 'group:1', 'msg-1')

    assert store.set_image_discussion(
        image_id, 'selected', 'api_key=abcdefghijklmno',
        context_text='bearer abcdefghijklmnopqrstuvwxyz', evidence_ids=[evidence_id], version=3,
    )

    discussion = store.image_discussion(image_id)
    assert discussion['image_id'] == image_id
    assert discussion['scope'] == 'group:1'
    assert discussion['status'] == 'selected'
    assert '[已脱敏]' in discussion['reason']
    assert '[已脱敏]' in discussion['context_text']
    assert discussion['evidence_ids'] == [evidence_id]
    assert discussion['manual'] == 0
    assert discussion['version'] == 3
    assert store.image_discussion(image_id)['updated_at']


def test_image_discussion_rejects_cross_scope_evidence(tmp_path):
    store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')
    other_evidence_id = _message(store, 'group:2', 'msg-2')

    with pytest.raises(ValueError, match='evidence'):
        store.set_image_discussion(image_id, 'pending', 'reason', evidence_ids=[other_evidence_id])
    assert store.image_discussion(image_id) is None


def test_manual_discussion_has_priority_and_can_be_updated_manually(tmp_path):
    store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')

    assert store.set_image_discussion(image_id, 'rejected', 'human review', manual=True, version=4)
    assert not store.set_image_discussion(image_id, 'selected', 'automatic', version=5)
    current = store.image_discussion(image_id)
    assert current['status'] == 'rejected'
    assert current['reason'] == 'human review'
    assert current['manual'] == 1
    assert current['version'] == 4

    assert store.set_image_discussion(image_id, 'selected', 'human update', manual=True, version=6)
    current = store.image_discussion(image_id)
    assert current['status'] == 'selected'
    assert current['version'] == 6


def test_missing_discussion_is_none_and_existing_store_functions_work(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert store.image_discussion(999) is None
    store.record_message(scope='group:1', user_id='user', text='hello', raw={'message_id': 'old'})
    assert store.count_messages_after('group:1', 0) == 1
    assert store.image_discussion(999) is None


def test_image_discussion_validates_status_and_evidence_ids(tmp_path):
    store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')
    with pytest.raises(ValueError, match='status'):
        store.set_image_discussion(image_id, 'unknown', 'reason')
    with pytest.raises(ValueError, match='positive integers'):
        store.set_image_discussion(image_id, 'pending', 'reason', evidence_ids=[True])


def test_same_image_human_rejection_applies_only_in_same_group(tmp_path):
    store = Store(tmp_path / 'bot.db')
    original = _image(store, 'group:1')
    duplicate = _image(store, 'group:1')
    other_group = _image(store, 'group:2')
    with store._conn() as conn:
        conn.execute('UPDATE images SET sha256=?', ('identical-content',))
        conn.commit()
    store.set_image_discussion(original, 'rejected', '歌单封面', manual=True)
    store.set_image_discussion(duplicate, 'selected', 'automatic review')
    store.set_image_discussion(other_group, 'selected', 'automatic review')
    assert store.image_discussion(duplicate)['status'] == 'rejected'
    assert store.image_discussion(other_group)['status'] == 'selected'


def test_manual_write_between_auto_read_and_upsert_cannot_be_overwritten(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    manual_store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')
    real_conn = store._conn

    class CachedCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class InterleavedConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, args=()):
            cursor = self.conn.execute(sql, args)
            if sql.startswith('SELECT manual FROM image_discussions'):
                rows = cursor.fetchall()
                # Interleave a second connection after the automatic read has
                # finished, exactly before its INSERT/UPDATE executes.
                manual_store.set_image_discussion(image_id, 'rejected', '人工确认', manual=True)
                return CachedCursor(rows)
            return cursor

        def commit(self):
            self.conn.commit()

    @contextmanager
    def interleaved():
        with real_conn() as conn:
            yield InterleavedConnection(conn)

    monkeypatch.setattr(store, '_conn', interleaved)
    assert not store.set_image_discussion(image_id, 'selected', 'automatic')
    current = manual_store.image_discussion(image_id)
    assert current['status'] == 'rejected'
    assert current['manual'] == 1


def test_manual_rejection_updates_existing_and_legacy_duplicates_only(tmp_path):
    store = Store(tmp_path / 'bot.db')
    original = _image(store, 'group:1')
    existing = _image(store, 'group:1')
    legacy = _image(store, 'group:1')
    human_approved = _image(store, 'group:1')
    other_group = _image(store, 'group:2')
    with store._conn() as conn:
        conn.execute('UPDATE images SET sha256=?', ('same-content',))
        conn.commit()
    store.set_image_discussion(existing, 'selected', 'automatic')
    store.set_image_discussion(human_approved, 'selected', 'independent approval', manual=True)
    store.set_image_discussion(other_group, 'selected', 'other group')
    store.set_image_discussion(original, 'rejected', '歌单封面', manual=True)
    assert store.image_discussion(existing)['status'] == 'rejected'
    assert store.image_discussion(legacy)['status'] == 'rejected'
    assert store.image_discussion(human_approved)['status'] == 'selected'
    assert store.image_discussion(other_group)['status'] == 'selected'


def test_duplicate_rejection_is_resolved_atomically_at_write_time(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    manual_store = Store(tmp_path / 'bot.db')
    original = _image(store, 'group:1')
    duplicate = _image(store, 'group:1')
    with store._conn() as conn:
        conn.execute('UPDATE images SET sha256=?', ('same-content',))
        conn.commit()
    store.set_image_discussion(duplicate, 'selected', 'old automatic decision')
    real_conn = store._conn

    class InterleavedConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, args=()):
            if sql.lstrip().startswith('WITH rejection AS'):
                manual_store.set_image_discussion(original, 'rejected', '人工纠错', manual=True)
            return self.conn.execute(sql, args)

        def commit(self):
            self.conn.commit()

    @contextmanager
    def interleaved():
        with real_conn() as conn:
            yield InterleavedConnection(conn)

    monkeypatch.setattr(store, '_conn', interleaved)
    assert store.set_image_discussion(duplicate, 'selected', 'stale automatic result')
    assert manual_store.image_discussion(duplicate)['status'] == 'rejected'
    assert manual_store.image_discussion(original)['manual'] == 1


def test_unknown_empty_hash_does_not_link_different_pictures(tmp_path):
    store = Store(tmp_path / 'bot.db')
    original = _image(store, 'group:1')
    unrelated = _image(store, 'group:1')
    with store._conn() as conn:
        conn.execute("UPDATE images SET sha256=''")
        conn.commit()
    store.set_image_discussion(original, 'rejected', '歌单封面', manual=True)
    store.set_image_discussion(unrelated, 'selected', '独立技术图')
    assert store.image_discussion(unrelated)['status'] == 'selected'


@pytest.mark.parametrize('status,manual', [('selected', True), ('selected', False), ('pending', False), ('rejected', True)])
def test_visual_recheck_cannot_put_reviewed_originals_on_candidate_ttl(tmp_path, status, manual):
    store = Store(tmp_path / 'bot.db')
    image_id = _image(store, 'group:1')
    with store._conn() as conn:
        conn.execute("UPDATE images SET retention_reason='params_discussion',kept_path='original.png'")
        conn.commit()
    store.set_image_discussion(image_id, status, 'reviewed', manual=manual)
    candidates = store.vision_unchecked_images(categories=('params_discussion',))
    assert bool(candidates) == (status == 'selected' and not manual)
    assert not store.demote_image_to_candidate(image_id)
    with store._conn() as conn:
        row = conn.execute('SELECT retention_reason,kept_path FROM images WHERE id=?', (image_id,)).fetchone()
        assert tuple(row) == ('params_discussion', 'original.png')
    current = store.image_discussion(image_id)
    assert current['status'] == ('pending' if status == 'selected' and not manual else status)
    assert current['manual'] == int(manual)

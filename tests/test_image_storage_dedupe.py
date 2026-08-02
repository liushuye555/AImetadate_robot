from qq_onebot_whitelist.maintenance import deduplicate_image_storage
from qq_onebot_whitelist.store import Store


def test_deduplicate_image_storage_prefers_archive_and_updates_records(tmp_path):
    data = tmp_path / 'data'
    archive = data / 'images' / 'ai' / 'ab' / 'abcdef.jpg'
    candidate = data / 'images' / 'candidates' / 'ab' / 'abcdef.png'
    archive.parent.mkdir(parents=True)
    candidate.parent.mkdir(parents=True)
    archive.write_bytes(b'same')
    candidate.write_bytes(b'same')
    store = Store(data / 'bot.db')
    store.record_image(
        scope='group:1', user_id='u',
        result={'sha256': 'abcdef', 'kept_path': str(candidate), 'retention_reason': 'candidate'},
        raw={'message_db_id': 1},
    )
    store.record_image(
        scope='group:2', user_id='u',
        result={'sha256': 'abcdef', 'kept_path': None, 'retention_reason': 'candidate'},
        raw={'message_db_id': 2},
    )

    assert deduplicate_image_storage(tmp_path, store) == 1

    assert archive.exists()
    assert not candidate.exists()
    assert {row['kept_path'] for row in store.image_records_with_paths()} == {str(archive)}
    assert len(store.image_records_with_paths()) == 2


def test_new_archive_occurrence_updates_older_same_sha_path(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_image(
        scope='group:1', user_id='u',
        result={'sha256': 'abcdef', 'kept_path': 'candidates/abcdef.png', 'retention_reason': 'candidate'},
        raw={'message_db_id': 1},
    )
    store.record_image(
        scope='group:2', user_id='u',
        result={'sha256': 'abcdef', 'kept_path': 'ai/abcdef.png', 'retention_reason': 'positive_feedback'},
        raw={'message_db_id': 2},
    )

    assert {row['kept_path'] for row in store.image_records_with_paths()} == {'ai/abcdef.png'}

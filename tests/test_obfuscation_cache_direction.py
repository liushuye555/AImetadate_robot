import sqlite3

from qq_onebot_whitelist.store import Store


def test_legacy_image_hashes_migration_and_old_tuple_api(tmp_path):
    db = tmp_path / 'legacy.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE image_hashes (sha256 TEXT PRIMARY KEY, phash TEXT, updated_at TEXT)')
        conn.execute(
            'INSERT INTO image_hashes (sha256, phash) VALUES (?, ?)',
            ('legacy-sha', '123'),
        )

    store = Store(db)
    assert store.obfuscation_score('legacy-sha') is None
    assert store.obfuscation_details('legacy-sha') is None
    with sqlite3.connect(db) as conn:
        columns = {row[1]: row for row in conn.execute('PRAGMA table_info(image_hashes)')}
        assert columns['xfq_direction'][2].upper() == 'TEXT'
        assert columns['xfq_version'][2].upper() == 'INTEGER'
        assert columns['xfq_version'][4] == '0'


def test_directional_obfuscation_cache_round_trip_preserves_tuple_api(tmp_path, monkeypatch):
    import qq_onebot_whitelist.gilbert_obfuscation as gilbert

    monkeypatch.setattr(gilbert, 'DETECTOR_VERSION', 2, raising=False)
    store = Store(tmp_path / 'cache.db')
    store.save_obfuscation_score(
        'direction-sha', ratio=0.375, layers=3, obfuscated=True,
        confidence='confirmed', direction='decode', version=2,
    )

    assert store.obfuscation_score('direction-sha') == (0.375, 3, True, 'confirmed')
    assert store.obfuscation_details('direction-sha') == {
        'ratio': 0.375,
        'layers': 3,
        'obfuscated': True,
        'confidence': 'confirmed',
        'direction': 'decode',
        'detector_version': 2,
    }


def test_save_without_version_uses_current_detector_version(tmp_path, monkeypatch):
    import qq_onebot_whitelist.gilbert_obfuscation as gilbert

    monkeypatch.setattr(gilbert, 'DETECTOR_VERSION', 7, raising=False)
    store = Store(tmp_path / 'cache.db')
    store.save_obfuscation_score(
        'lazy-version-sha', ratio=0.4, layers=None,
        obfuscated=False, confidence='none', direction='encode',
    )
    assert store.obfuscation_details('lazy-version-sha')['detector_version'] == 7

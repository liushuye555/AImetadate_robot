import sqlite3

from qq_onebot_whitelist.store import Store


def test_clear_missing_image_paths(tmp_path):
    store = Store(tmp_path / 'bot.db')
    existing = tmp_path / 'data' / 'images' / 'ai' / 'ok.png'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'x')
    missing = tmp_path / 'data' / 'images' / 'ai' / 'missing.png'
    store.record_image(scope='group:1', user_id='u', result={
        'url': 'a', 'sha256': 'sha1', 'size': 1, 'format': 'PNG', 'width': 1, 'height': 1,
        'metadata_keys': [], 'has_ai_metadata': True, 'ai_source': 'ComfyUI', 'text_excerpt': '',
        'kept_path': str(existing), 'retention_reason': 'ai_metadata'
    }, raw={})
    store.record_image(scope='group:1', user_id='u', result={
        'url': 'b', 'sha256': 'sha2', 'size': 1, 'format': 'PNG', 'width': 1, 'height': 1,
        'metadata_keys': [], 'has_ai_metadata': False, 'ai_source': '', 'text_excerpt': '',
        'kept_path': str(missing), 'retention_reason': 'candidate'
    }, raw={})
    assert store.clear_missing_image_paths(tmp_path) == 1
    conn = sqlite3.connect(tmp_path / 'bot.db')
    rows = dict(conn.execute('SELECT sha256, kept_path FROM images').fetchall())
    conn.close()
    assert rows['sha1'] == str(existing)
    assert rows['sha2'] is None


def test_restore_confirmed_obfuscation_replaces_and_marks(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import restore_confirmed_obfuscation
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    archive = data / "images" / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    restored_file = tmp_path / "restored" / "abc.png"
    restored_file.parent.mkdir(parents=True)
    restored_file.write_bytes(b"restored-content")

    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(original), "retention_reason": "xiaofanqie_obfuscated",
    }, raw={})
    store.save_obfuscation_score("abc", ratio=0.5, layers=1, obfuscated=True, confidence="confirmed")

    def fake_restore(src, out, layers=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"restored-content")
        return out, 1

    import qq_onebot_whitelist.maintenance as m
    monkeypatch.setattr(m, "restore_image", fake_restore)

    changed = restore_confirmed_obfuscation(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT kept_path, restored_path, deobfuscated FROM images WHERE sha256='abc'").fetchone()
    conn.close()
    assert row[2] == 1
    assert row[1] == row[0]
    assert Path(row[0]).read_bytes() == b"restored-content"


def test_restore_confirmed_obfuscation_skips_missing_restored(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import restore_confirmed_obfuscation
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    archive = data / "images" / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(original), "retention_reason": "xiaofanqie_obfuscated",
    }, raw={})
    store.save_obfuscation_score("abc", ratio=0.5, layers=1, obfuscated=True, confidence="confirmed")

    def fake_restore(src, out, layers=None):
        raise FileNotFoundError("restore failed")

    import qq_onebot_whitelist.maintenance as m
    monkeypatch.setattr(m, "restore_image", fake_restore)

    changed = restore_confirmed_obfuscation(tmp_path)
    assert changed == 0
    assert original.exists()


def test_reclassify_historical_03(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import reclassify_historical_03
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    img = data / "images" / "ai" / "ab" / "abc.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    store.record_message(scope="group:1", user_id="u", text="/绘图 文生图 fox girl", raw={"message_id": "m1"})
    msg_id = store.message_row_id("group:1", {"message_id": "m1"})
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "nearby_ai_context",
        "text_excerpt": "",
    }, raw={"message_db_id": msg_id})
    changed = reclassify_historical_03(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, bound_prompt FROM images").fetchone()
    conn.close()
    assert row[0] == "prompt_bound"


def test_backfill_prompt_keys(tmp_path):
    import sqlite3, hashlib
    from qq_onebot_whitelist.maintenance import backfill_prompt_keys
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    img = data / "a.png"
    img.write_bytes(b"x")
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "a", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "ai_metadata",
        "text_excerpt": "1girl, solo", "ai_source": "ComfyUI",
    }, raw={})
    changed = backfill_prompt_keys(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    pk = conn.execute("SELECT prompt_key FROM images").fetchone()[0]
    conn.close()
    assert pk == hashlib.sha1(b"1girl, solo").hexdigest()[:16]

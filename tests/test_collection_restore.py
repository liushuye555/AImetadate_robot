"""入库时混淆图还原即替换测试。"""


def test_process_event_image_replaces_with_restored(tmp_path, monkeypatch):
    from pathlib import Path
    import qq_onebot_whitelist.collection as collection
    from qq_onebot_whitelist.config import AppConfig
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    config = AppConfig(data_dir=data)
    archive = data / "images" / "ai"
    original = archive / "ab" / "abc.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"obfuscated")
    restored = data / "tmp" / "restored.png"
    restored.parent.mkdir(parents=True)
    restored.write_bytes(b"restored-content")

    def fake_process_image_url(url, **kwargs):
        return {
            "url": url, "sha256": "abc", "phash": None, "blockiness": 0.0,
            "size": 10, "format": "PNG", "width": 4, "height": 4,
            "metadata_keys": [], "has_ai_metadata": False, "ai_source": None,
            "text_excerpt": "", "kept_path": str(original), "retention_reason": "candidate",
        }

    def fake_analyze(path):
        return {"obfuscated": True, "confidence": "confirmed", "ratio": 0.5, "layers": 1}

    def fake_restore(src, out, layers=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"restored-content")
        return out, 1

    monkeypatch.setattr(collection, "process_image_url", fake_process_image_url)
    monkeypatch.setattr(collection, "analyze_image", fake_analyze)
    monkeypatch.setattr(collection, "restore_image", fake_restore)

    image = {"url": "http://x/img.png", "file": "img.png"}
    collection.process_event_image(
        store, scope="group:1", user_id="u", image=image,
        nearby_text="", message_db_id=None, config=config,
    )

    import sqlite3
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, kept_path, deobfuscated, restored_path FROM images").fetchone()
    conn.close()
    assert row[0] == "xiaofanqie_obfuscated"
    assert row[1] == str(archive / "ab" / "abc.png")
    assert row[2] == 1
    assert row[3] == row[1]
    assert (archive / "ab" / "abc.png").read_bytes() == b"restored-content"


def test_process_event_image_prompt_bound(tmp_path, monkeypatch):
    import sqlite3
    import qq_onebot_whitelist.collection as collection
    from qq_onebot_whitelist.config import AppConfig
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    config = AppConfig(data_dir=data)
    img = data / "images" / "ai" / "ab" / "abc.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")

    def fake_process_image_url(url, **kwargs):
        return {"url": url, "sha256": "abc", "phash": None, "blockiness": 0.0, "size": 1,
                "format": "PNG", "width": 4, "height": 4, "metadata_keys": [],
                "has_ai_metadata": False, "ai_source": None, "text_excerpt": "",
                "kept_path": str(img), "retention_reason": "candidate"}

    def fake_bind(records, reply_to=None, own_message_id=None):
        return "prompt", "1girl, solo"

    monkeypatch.setattr(collection, "process_image_url", fake_process_image_url)
    monkeypatch.setattr(collection, "bind_prompt_for_image", fake_bind)
    monkeypatch.setattr(collection, "analyze_image", lambda p: None)

    collection.process_event_image(store, scope="group:1", user_id="u",
        image={"url": "http://x/i.png"}, nearby_text="", message_db_id=1, config=config)

    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, bound_prompt FROM images").fetchone()
    conn.close()
    assert row == ("prompt_bound", "1girl, solo")

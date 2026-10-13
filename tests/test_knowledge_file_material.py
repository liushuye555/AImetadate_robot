import hashlib

import yaml

from qq_onebot_whitelist import knowledge_file_material as material
from qq_onebot_whitelist import knowledge_files


def _config(path, *, enabled=True, preview=True):
    value = {
        "onebot": {"ws_url": "ws://127.0.0.1:3001"},
        "knowledge": {
            "enabled": True,
            "defaults": {"files": {"enabled": False}},
            "groups": {"group:123": {
                "enabled": True,
                "files": {"enabled": enabled, "preview_enabled": preview},
            }},
        },
    }
    path.write_text(yaml.safe_dump(value), encoding="utf-8")


def test_requires_both_explicit_gates_and_does_not_download(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    _config(config, enabled=False, preview=True)
    calls = []
    monkeypatch.setattr(material, "fetch_download_url_once", lambda *a, **k: calls.append(a))
    record = {"scope": "group:123", "files": [{"file_id": "f", "file_name": "a.txt"}]}
    result = material.prepare_file_previews(config, "group:123", [record])
    assert result == [record]
    assert calls == []

    _config(config, enabled=True, preview=False)
    assert material.prepare_file_previews(config, "group:123", [record]) == [record]
    assert calls == []


def test_download_hash_preview_and_input_copy(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    _config(config)
    payload = b"title: example\napi_key=very-secret-value\n"
    calls = []

    def fake_url(group, file_id, busid=None, **kwargs):
        calls.append((group, file_id, busid))
        return "https://unit.test/signed"

    def fake_download(url, staging, *, max_bytes):
        assert url == "https://unit.test/signed"
        assert max_bytes <= 256 * 1024
        staging.write_bytes(payload)
        return staging

    monkeypatch.setattr(material, "fetch_download_url_once", fake_url)
    monkeypatch.setattr(knowledge_files, "download_to_staging", fake_download)
    original = {"scope": "group:123", "files": [{"file_id": "f1", "file_name": "flow.yaml",
                                                   "file_size": len(payload)}]}
    result = material.prepare_file_previews(config, "group:123", [original])
    preview = result[0]["files"][0]["preview"]
    assert calls == [("123", "f1", None)]
    assert preview["status"] == "ready"
    assert preview["size"] == len(payload)
    assert preview["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "very-secret-value" not in preview["text"]
    assert "preview" not in original["files"][0]


def test_forwards_busid_when_refreshing_onebot_url(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    _config(config)
    seen = []
    monkeypatch.setattr(material, "fetch_download_url_once",
                        lambda group, fid, busid=None, **kwargs: seen.append(busid) or "https://unit.test/file")
    def fake_download(_url, staging, **_kwargs):
        staging.write_bytes(b"x")
        return staging
    monkeypatch.setattr(knowledge_files, "download_to_staging", fake_download)
    record = {"scope": "group:123", "files": [{"file_id": "/550e8400-e29b-41d4-a716-446655440000",
                                                  "file_name": "a.txt", "file_size": 1,
                                                  "busid": 17}]}
    material.prepare_file_previews(config, "group:123", [record])
    assert seen == [17]


def test_processes_at_most_three_files(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    _config(config)
    calls = []
    payload = b"hello"
    monkeypatch.setattr(material, "fetch_download_url_once",
                        lambda group, fid, busid=None, **kwargs: calls.append(fid) or "https://unit.test/file")

    def fake_download(_url, staging, *, max_bytes):
        staging.write_bytes(payload)
        return staging

    monkeypatch.setattr(knowledge_files, "download_to_staging", fake_download)
    files = [{"file_id": str(i), "file_name": f"{i}.txt", "file_size": len(payload)} for i in range(4)]
    rows = material.prepare_file_previews(config, "group:123", [{"scope": "group:123", "files": files}])
    assert calls == ["0", "1", "2"]
    assert all("preview" in f for f in rows[0]["files"][:3])
    assert "preview" not in rows[0]["files"][3]


def test_unsupported_extension_is_skipped_before_url_fetch(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    _config(config)
    monkeypatch.setattr(material, "fetch_download_url_once",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must skip before URL")))
    record = {"scope": "group:123", "files": [{"file_id": "binary-id", "file_name": "model.safetensors"}]}
    result = material.prepare_file_previews(config, "group:123", [record])
    assert result[0]["files"][0]["preview"]["status"] == "unsupported"
    assert result[0]["files"][0]["preview"]["error"] == "UnsupportedFormat"

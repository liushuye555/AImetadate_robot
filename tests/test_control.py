import json

from qq_onebot_whitelist import control


def test_write_status_is_atomic_and_contains_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    control.write_status({"napcat": True, "onebot": True, "bot": True})
    target = tmp_path / "status.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["napcat"] is True
    assert data["updatedAt"]


def test_load_status_returns_empty_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    assert control.load_status() == {}


def test_port_open_false_when_closed(monkeypatch):
    def fake(port, timeout):
        raise OSError("closed")
    monkeypatch.setattr(control.socket, "create_connection", fake)
    assert control.port_open(6099) is False

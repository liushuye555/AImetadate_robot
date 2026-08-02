import itertools
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


def test_start_uses_expected_commands(tmp_path, monkeypatch):
    started = []

    def fake_popen(cmd, **kwargs):
        started.append(cmd)

        class P:
            pid = 42
        return P()

    napcat_bat = tmp_path / "runtime" / "NapCat.Shell.Windows.Node" / "napcat.bat"
    napcat_bat.parent.mkdir(parents=True)
    napcat_bat.write_text("@echo off", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("bot:\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()

    monkeypatch.setattr(control, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: False)
    monkeypatch.setattr(control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(control.time, "sleep", lambda _s: None)
    clock = iter(itertools.count(0, 3))
    monkeypatch.setattr(control.time, "time", lambda: next(clock))
    monkeypatch.setattr(control, "ONEBOT_PORT", 3001)
    monkeypatch.setattr(control, "NAPCAT_PORT", 6099)

    control.start_services()
    joined = " ".join(" ".join(part) if isinstance(part, (list, tuple)) else str(part) for part in started)
    assert "napcat.bat" in joined
    assert "qq_onebot_whitelist.onebot" in joined


def test_stop_kills_pid_files(tmp_path, monkeypatch):
    killed = []

    def fake_run(cmd, **kwargs):
        killed.append(cmd)
        return None

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    (tmp_path / "napcat.pid").write_text("111\n", encoding="ascii")
    (tmp_path / "bot.pid").write_text("222\n", encoding="ascii")
    monkeypatch.setattr(control.subprocess, "run", fake_run)

    control.stop_services()
    assert any("111" in " ".join(c) for c in killed)
    assert any("222" in " ".join(c) for c in killed)


def test_stats_counts(monkeypatch):
    class FakeStore:
        def recent_files(self, **kw):
            return [{"file_name": "a.zip"}, {"file_name": "b.zip"}]

        def recent_link_records(self, **kw):
            return [{"url": "https://x"}, {"url": "https://y"}]

        def last_daily_report_sent_at(self):
            return None

    monkeypatch.setattr(
        "qq_onebot_whitelist.maintenance.sync_image_files",
        lambda project_dir: {
            "image_duplicates_removed": 0,
            "missing_cleared": 0,
            "empty_candidate_dirs": 0,
            "01_AI元数据": 8,
            "02_群友好评": 4,
            "resource_links": 5,
            "resource_files": 3,
        },
    )
    out = control.build_stats(FakeStore())
    assert out["images"] == 12
    assert out["links"] == 2
    assert out["lastReport"] is None


def test_cmd_stats_prints_json(capsys, monkeypatch):
    monkeypatch.setattr(control, "load_stats", lambda: {"images": 1, "links": 2, "lastReport": None})
    assert control.cmd_stats(None) == 0
    assert "images" in capsys.readouterr().out


def test_report_preview_builds_text(monkeypatch):
    class FakeStore:
        def last_daily_report_sent_at(self):
            return None

    class FakeConfig:
        daily_report_enrich_links = True
        feature_link_metadata = True
        feature_link_analysis = True
        daily_report_max_links = 20
        daily_report_max_enriched_links = 8
        language = "zh-CN"

    monkeypatch.setattr(
        "qq_onebot_whitelist.daily_report.build_daily_resource_report",
        lambda store, **kw: "日报内容",
    )
    assert control.build_report_preview(FakeStore(), FakeConfig()) == "日报内容"


def test_cmd_report_preview_prints_json(capsys, monkeypatch):
    monkeypatch.setattr(control, "load_report_preview", lambda: ("内容", 2))
    assert control.cmd_report_preview(None) == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out and "内容" in out

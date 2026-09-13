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
    # Windows 引号转义回归：napcat 启动参数不能含被转义的引号（\"），否则 cmd 无法执行
    assert not any("\\\"" in str(part) for cmd in started for part in cmd)


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
    assert (tmp_path / "manual-stop").exists()
    assert control.load_status()["manualStop"] is True
    assert control.load_status()["bot"] is False



def test_stop_publishes_manual_stop_before_killing(tmp_path, monkeypatch):
    observed = []

    def fake_run(cmd, **kwargs):
        status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
        observed.append(((tmp_path / "manual-stop").exists(), status["manualStop"]))
        return None

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    (tmp_path / "bot.pid").write_text("222\n", encoding="ascii")
    monkeypatch.setattr(control.subprocess, "run", fake_run)

    control.stop_services()

    assert observed == [(True, True)]

def test_start_clears_manual_stop_marker(tmp_path, monkeypatch):
    napcat_bat = tmp_path / "runtime" / "NapCat.Shell.Windows.Node" / "napcat.bat"
    napcat_bat.parent.mkdir(parents=True)
    napcat_bat.write_text("@echo off", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("bot:\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "manual-stop").write_text("stop", encoding="ascii")

    monkeypatch.setattr(control, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: True)
    monkeypatch.setattr(control.subprocess, "Popen", lambda *args, **kwargs: type("P", (), {"pid": 42})())

    control.start_services(clear_manual_stop=True)
    assert not (tmp_path / "manual-stop").exists()


def test_bot_restart_respects_manual_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    (tmp_path / "manual-stop").write_text("stop", encoding="ascii")
    monkeypatch.setattr(control, "start_services", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not start")))

    assert control.cmd_bot_restart(None) == 0


def test_pid_running_uses_windows_safe_probe(tmp_path, monkeypatch):
    pid_path = tmp_path / "bot.pid"
    pid_path.write_text("42", encoding="ascii")
    calls = []

    class FakeOS:
        name = "nt"

        @staticmethod
        def kill(*args):
            raise AssertionError("Windows PID probe must not call os.kill")

    monkeypatch.setattr(control, "os", FakeOS)
    monkeypatch.setattr(control, "_windows_pid_running", lambda pid: calls.append(pid) or True)

    assert control.pid_running(pid_path) is True
    assert calls == [42]


def test_live_status_uses_current_process_and_ports(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: port in {6099, 3001})
    monkeypatch.setattr(control, "pid_running", lambda path: path.name == "bot.pid")
    (tmp_path / "bot.pid").write_text("42", encoding="ascii")
    (tmp_path / "manual-stop").write_text("stop", encoding="ascii")
    (tmp_path / "status.json").write_text(
        '{"qqNumber":"123","qqNickname":"昵称"}', encoding="utf-8"
    )

    status = control.live_status()

    assert status["napcat"] is True
    assert status["onebot"] is True
    assert status["bot"] is True
    assert status["qqLoggedIn"] is True
    assert status["manualStop"] is True
    assert status["qqNumber"] == ""
    assert status["updatedAt"]


def test_live_status_survives_corrupt_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: False)
    monkeypatch.setattr(control, "pid_running", lambda path: False)
    (tmp_path / "status.json").write_text("not-json", encoding="utf-8")

    status = control.live_status()

    assert status["napcat"] is False
    assert status["onebot"] is False
    assert status["bot"] is False
    assert status["qqNumber"] == ""


def test_cmd_live_status_prints_json(capsys, monkeypatch):
    monkeypatch.setattr(control, "live_status", lambda: {"bot": True})

    assert control.cmd_live_status(None) == 0

    assert '"bot": true' in capsys.readouterr().out


def test_stats_counts_real_db(tmp_path):
    import sqlite3

    from qq_onebot_whitelist.store import Store

    store = Store(tmp_path / "bot.db")
    store.record_link(scope="g1", user_id="u1", url="https://x", message_text="hi", quoted_text="", kind="link")
    conn = sqlite3.connect(store.path)
    conn.execute("INSERT INTO images (scope, user_id, sha256) VALUES (?, ?, ?)", ("g1", "u1", "abc"))
    conn.commit()
    conn.close()
    out = control.build_stats(store)
    assert out["links"] == 1
    assert out["images"] == 1
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
        daily_report_include_files = True
        daily_report_include_links = True
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

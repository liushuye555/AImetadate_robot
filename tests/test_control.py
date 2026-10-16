import json

from qq_onebot_whitelist import control
from qq_onebot_whitelist.manager_owner import ManagerRequiredError


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


def test_owned_status_rejects_stale_manager_even_with_live_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(control, 'RUN_DIR', tmp_path)
    (tmp_path / 'bot-owner.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'manager-session.json').write_text(
        '{"pid":42,"created":"123","session":"old"}', encoding='utf-8')
    monkeypatch.setattr(control, 'is_process_alive', lambda *_: False)
    monkeypatch.setattr(control, 'pid_running', lambda *_: True)
    monkeypatch.setattr(control, 'read_owned_bot', lambda *_: 99)
    assert control.owned_bot_running() is False


def test_port_open_false_when_closed(monkeypatch):
    def fake(port, timeout):
        raise OSError("closed")
    monkeypatch.setattr(control.socket, "create_connection", fake)
    assert control.port_open(6099) is False


def test_start_services_refuses_external_process(monkeypatch):
    monkeypatch.setattr(
        control, "require_manager",
        lambda _root: (_ for _ in ()).throw(ManagerRequiredError("manager required")),
    )
    monkeypatch.setattr(
        control.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )

    try:
        control.start_services()
    except ManagerRequiredError:
        pass
    else:
        raise AssertionError("external direct start must be refused")


def test_external_commands_forward_to_manager(monkeypatch):
    forwarded = []
    monkeypatch.setattr(control, "managed_context", lambda _root: False)
    monkeypatch.setattr(control, "request_manager", lambda action="show": forwarded.append(action) or 0)
    monkeypatch.setattr(
        control, "start_services",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("external command must not start services")),
    )

    assert control.cmd_start(None) == 0
    assert control.cmd_restart(None) == 0
    assert control.cmd_stop(None) == 0
    assert forwarded == ["show", "restart-services", "stop-services"]


def test_start_services_is_idempotent_for_current_manager_session(tmp_path, monkeypatch):
    session = {"session": "test-session"}
    read_calls = []
    monkeypatch.setattr(control, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(control, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(control, "require_manager", lambda _root: session)
    monkeypatch.setattr(
        control, "read_owned_bot",
        lambda _root, current: read_calls.append(current) or 2468,
    )
    monkeypatch.setattr(
        control.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("owned bot already exists")),
    )

    assert control.start_services() == 2468
    assert control.start_services() == 2468
    assert read_calls == ["test-session", "test-session"]


def test_start_services_breaks_napcat_out_of_job_and_keeps_bot_in_job(tmp_path, monkeypatch):
    spawned = []

    def fake_popen(command, **kwargs):
        spawned.append((command, kwargs))
        return type("Process", (), {"pid": 100 + len(spawned)})()

    napcat_bat = tmp_path / "runtime" / "NapCat.Shell.Windows.Node" / "napcat.bat"
    napcat_bat.parent.mkdir(parents=True)
    napcat_bat.write_text("@echo off", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("bot:\n", encoding="utf-8")
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fake executable")

    monkeypatch.setattr(control, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(control, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(control, "require_manager", lambda _root: {"session": "active-session"})
    monkeypatch.setattr(control, "read_owned_bot", lambda *_args: None)
    monkeypatch.setattr(control, "_retire_legacy_bots", lambda: None)
    monkeypatch.setattr(control, "port_open", lambda _port: False)
    monkeypatch.setattr(control, "save_bot_owner", lambda *_args: None)
    monkeypatch.setattr(control.subprocess, "Popen", fake_popen)

    assert control.start_services() == 102

    napcat_command, napcat_options = spawned[0]
    bot_command, bot_options = spawned[1]
    assert "napcat.bat" in napcat_command[-1]
    assert napcat_options["creationflags"] & getattr(control.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    assert bot_command == [str(python), "-u", "-m", "qq_onebot_whitelist.onebot", "--config", str(config)]
    assert not bot_options["creationflags"] & getattr(control.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    assert (tmp_path / "run" / "napcat.pid").read_text(encoding="ascii") == "101"
    assert (tmp_path / "run" / "bot.pid").read_text(encoding="ascii") == "102"


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

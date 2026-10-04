import sqlite3
import json
from pathlib import Path

import pytest

from qq_onebot_whitelist import backup
from qq_onebot_whitelist.config import load_config


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "bot.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('x')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def state_path(tmp_path, monkeypatch):
    # 状态文件指向临时目录，避免测试污染真实 run/
    target = tmp_path / "state" / "backup-state.json"
    monkeypatch.setattr(backup, "STATE_PATH", target)
    monkeypatch.setattr(backup, "RUN_DIR", target.parent)
    return target


def test_snapshot_creates_verified_copy(db, tmp_path):
    target = tmp_path / "backups"
    snapshot = backup.snapshot_database(db, target, "daily")
    assert snapshot.exists()
    assert snapshot.name.startswith("bot-daily-")
    conn = sqlite3.connect(snapshot)
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_run_backup_writes_state_and_config(db, tmp_path):
    target = tmp_path / "backups"
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("onebot:\n  ws_url: ws://x\n", encoding="utf-8")
    result = backup.run_backup(db, target, config_yaml=config_yaml)
    assert result["backupOk"] is True
    assert result["error"] is None
    assert list(target.glob("bot-*.db"))
    assert list(target.glob("config-*.yaml"))
    state = json.loads(backup.STATE_PATH.read_text(encoding="utf-8"))
    assert state["backupOk"] is True
    assert state["lastBackup"] == result["lastBackup"]


def test_run_backup_failure_records_error(tmp_path):
    result = backup.run_backup(tmp_path / "missing.db", tmp_path / "backups")
    assert result["backupOk"] is False
    assert "FileNotFoundError" in (result["error"] or "")
    state = backup.read_state()
    assert state["backupOk"] is False


def test_run_backup_skips_when_disk_full(db, tmp_path, monkeypatch):
    import qq_onebot_whitelist.backup as mod

    def fake_disk(path):
        class Usage:
            free = 100 * 1024 * 1024  # 100MB < 2048MB 默认阈值

        return Usage()

    monkeypatch.setattr(mod.shutil, "disk_usage", fake_disk)
    result = backup.run_backup(db, tmp_path / "backups", min_free_mb=2048)
    assert result["backupOk"] is False
    assert "min_free_mb" in (result["error"] or "")


def test_retention_keeps_daily_and_weekly_pools(db, tmp_path):
    target = tmp_path / "backups"
    target.mkdir()
    for i in range(5):
        (target / f"bot-daily-2026100{i}-120000.db").write_bytes(b"x")
    (target / "bot-weekly-20260928-120000.db").write_bytes(b"x")
    (target / "bot-pre-test-20260901-000000.db").write_bytes(b"x")

    backup.run_backup(db, target, keep_daily=2, keep_weekly=2, force_kind="daily")

    dailies = sorted(target.glob("bot-daily-*.db"))
    weeklies = sorted(target.glob("bot-weekly-*.db"))
    # 旧的 4 份日备 + 本次新生成 1 份 = 6，keep_daily=2 → 剩 2
    assert len(dailies) == 2
    assert len(weeklies) == 1  # 只剩预置的旧周备（本次快照是 daily）
    # pre-* 快照不受轮换影响
    assert (target / "bot-pre-test-20260901-000000.db").exists()


def test_pre_operation_snapshot_naming(db, tmp_path):
    target = tmp_path / "backups"
    snapshot = backup.pre_operation_snapshot(db, target, "结构化重分类!")
    assert snapshot.name.startswith("bot-pre-")
    assert snapshot.exists()


def test_mirror_images_rejects_overlap(tmp_path):
    source = tmp_path / "images"
    source.mkdir()
    info = backup.mirror_images(source, source)
    assert info["ok"] is False
    info = backup.mirror_images(source, tmp_path)
    assert info["ok"] is False


def test_config_backup_section(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        "backup:\n"
        "  enabled: false\n"
        "  dir: D:/bot-backups\n"
        "  keep_daily: 5\n"
        "  keep_weekly: 1\n"
        "  min_free_mb: 4096\n"
        "  images: true\n"
        "  images_dir: E:/bot-backups\n",
        encoding="utf-8",
    )
    config = load_config(config_yaml)
    assert config.backup_enabled is False
    assert str(config.backup_dir) == str(Path("D:/bot-backups"))
    assert config.backup_keep_daily == 5
    assert config.backup_keep_weekly == 1
    assert config.backup_min_free_mb == 4096
    assert config.backup_images is True
    assert str(config.backup_images_dir) == str(Path("E:/bot-backups"))

    defaults = load_config(tmp_path / "missing.yaml")
    assert defaults.backup_enabled is True
    assert str(defaults.backup_dir) == str(Path("data/backups"))
    assert defaults.backup_images is False
    assert defaults.backup_images_dir is None

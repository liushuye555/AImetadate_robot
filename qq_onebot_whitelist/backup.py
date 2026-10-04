"""分层备份：每日 DB 快照（VACUUM INTO 在线一致）+ 周备轮换 + config 归档 + 可选图片镜像。

状态写入 run/backup-state.json，bot 的 status_writer_loop 与 control backup 共用，
谁执行备份谁刷新状态，避免 status.json 整体覆写互相覆盖。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "run"
STATE_PATH = RUN_DIR / "backup-state.json"

_DAILY_PATTERN = re.compile(r"^bot-daily-\d{8}-\d{6}\.db$")
_WEEKLY_PATTERN = re.compile(r"^bot-weekly-\d{8}-\d{6}\.db$")


def read_state() -> dict:
    try:
        return dict(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(f".json.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _prune(directory: Path, pattern: re.Pattern[str], keep: int) -> list[str]:
    files = sorted(p for p in directory.iterdir() if p.is_file() and pattern.match(p.name))
    removed = []
    for path in files[:-keep] if keep > 0 else files:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def _integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(path, timeout=30)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    finally:
        conn.close()


def _slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", cleaned)[:40] or "op"


def snapshot_database(db_path: Path, target_dir: Path, kind: str, *, reason: str = "") -> Path:
    """VACUUM INTO 出一份事务一致的压缩副本；先写 .tmp 再原子改名。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{_slug(reason)}" if reason else ""
    final = target_dir / f"bot-{kind}{suffix}-{stamp}.db"
    tmp = target_dir / f".vacuum-{stamp}-{os.getpid()}.tmp"
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        conn.close()
    if not _integrity_ok(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("integrity_check failed on fresh snapshot")
    os.replace(tmp, final)
    return final


def pre_operation_snapshot(db_path: Path, target_dir: Path, reason: str) -> Path:
    return snapshot_database(db_path, target_dir, "pre", reason=reason)


def mirror_images(source: Path, target: Path) -> dict:
    """robocopy 增量镜像（只新增/更新，不删除目标多余文件）。返回摘要。"""
    source = source.resolve()
    target = Path(target).resolve()
    if target == source or target in source.parents or source in target.parents:
        return {"ok": False, "error": "images_dir 不能与 data/images 重叠"}
    started = time.monotonic()
    result = subprocess.run(
        ["robocopy", str(source), str(target), "/E", "/R:2", "/W:5",
         "/NFL", "/NDL", "/NP", "/MT:8"],
        capture_output=True, text=True, check=False,
    )
    # robocopy 退出码 0-7 均为成功（1=有新文件拷贝），>=8 才是失败
    ok = result.returncode < 8
    return {
        "ok": ok,
        "exitCode": result.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "error": None if ok else (result.stderr or result.stdout or "").strip()[-400:],
    }


def run_backup(
    db_path: Path,
    target_dir: Path,
    *,
    keep_daily: int = 3,
    keep_weekly: int = 2,
    min_free_mb: int = 2048,
    config_yaml: Path | None = None,
    images_source: Path | None = None,
    images_target: Path | None = None,
    force_kind: str | None = None,
) -> dict:
    """执行一次完整备份并刷新状态文件；返回结果字典（也持久化到 backup-state.json）。"""
    started = time.monotonic()
    db_path = Path(db_path)
    target_dir = Path(target_dir)
    state: dict = {"lastBackup": "", "backupOk": False, "error": None}
    try:
        if not db_path.exists():
            raise FileNotFoundError(f"数据库不存在: {db_path}")
        target_dir.mkdir(parents=True, exist_ok=True)
        free_mb = shutil.disk_usage(target_dir).free // (1024 * 1024)
        if free_mb < min_free_mb:
            raise RuntimeError(f"目标盘剩余 {free_mb}MB，低于 min_free_mb={min_free_mb}，跳过备份")

        now = datetime.now()
        kind = force_kind or ("weekly" if now.weekday() == 0 else "daily")
        snapshot = snapshot_database(db_path, target_dir, kind)
        removed_db = _prune(target_dir, _DAILY_PATTERN, keep_daily)
        removed_db += _prune(target_dir, _WEEKLY_PATTERN, keep_weekly)

        removed_cfg: list[str] = []
        if config_yaml and Path(config_yaml).exists():
            cfg_stamp = now.strftime("%Y%m%d-%H%M%S")
            cfg_target = target_dir / f"config-{cfg_stamp}.yaml"
            shutil.copyfile(config_yaml, cfg_target)
            cfg_files = sorted(target_dir.glob("config-*.yaml"))
            for old in cfg_files[:-max(1, keep_daily)]:
                try:
                    old.unlink()
                    removed_cfg.append(old.name)
                except OSError:
                    pass

        images_info: dict = {}
        if images_source and images_target:
            images_info = mirror_images(images_source, images_target)

        state = {
            "lastBackup": now.strftime("%Y-%m-%d %H:%M"),
            "backupOk": True,
            "kind": kind,
            "file": snapshot.name,
            "sizeMB": round(snapshot.stat().st_size / (1024 * 1024), 1),
            "seconds": round(time.monotonic() - started, 1),
            "pruned": removed_db,
            "error": None,
            "images": images_info or None,
        }
        return state
    except Exception as exc:
        state = {
            "lastBackup": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "backupOk": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }
        return state
    finally:
        _write_state(state)
        print(f"backup: ok={state.get('backupOk')} {state.get('file', state.get('error'))}"
              f" 用时 {round(time.monotonic() - started, 1)}s")

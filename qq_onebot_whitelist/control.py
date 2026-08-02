"""Control bridge used by the Qt panel; keeps operational logic in Python."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "run"
STATUS_PATH = RUN_DIR / "status.json"
NAPCAT_PORT = 6099
ONEBOT_PORT = 3001


def status_path() -> Path:
    return RUN_DIR / "status.json"


def write_status(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = status_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(status_path())


def load_status() -> dict:
    if not status_path().exists():
        return {}
    return json.loads(status_path().read_text(encoding="utf-8"))


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def start_services() -> None:
    """启动 NapCat 与机器人（迁移自 start-qq-onebot-whitelist-hidden.ps1 的核心逻辑）。"""
    napcat_dir = REPO_ROOT / "runtime" / "NapCat.Shell.Windows.Node"
    napcat_bat = napcat_dir / "napcat.bat"
    if not napcat_bat.exists():
        raise RuntimeError(f"NapCat launcher not found: {napcat_bat}")
    config = REPO_ROOT / "config.yaml"
    if not config.exists():
        raise RuntimeError(f"Bot config not found: {config}")

    if not port_open(NAPCAT_PORT):
        pid = subprocess.Popen(
            ["cmd.exe", "/d", "/s", "/c", f'call "{napcat_bat}"'],
            cwd=str(napcat_dir),
            stdout=open(REPO_ROOT / "logs" / "napcat.log", "a", encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).pid
        (RUN_DIR / "napcat.pid").write_text(str(pid), encoding="ascii")

    deadline = time.time() + 300
    while time.time() < deadline:
        if port_open(ONEBOT_PORT):
            break
        time.sleep(3)

    if not port_open(ONEBOT_PORT):
        print("OneBot WS port not ready; bot will retry connecting. NapCat WebUI: http://127.0.0.1:6099")

    # bot 自身不监听端口，直接尝试启动（计划中已注明简化：幂等检查暂省略）
    bot_pid = subprocess.Popen(
        ["uv", "run", "python", "-m", "qq_onebot_whitelist.onebot", "--config", str(config)],
        cwd=str(REPO_ROOT),
        stdout=open(REPO_ROOT / "logs" / "bot.log", "a", encoding="utf-8", errors="replace"),
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).pid
    (RUN_DIR / "bot.pid").write_text(str(bot_pid), encoding="ascii")


def stop_services() -> None:
    for name in ("napcat.pid", "bot.pid"):
        pid_path = RUN_DIR / name
        if not pid_path.exists():
            continue
        pid = pid_path.read_text(encoding="ascii").strip()
        if pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        pid_path.unlink(missing_ok=True)


def cmd_start(args: argparse.Namespace) -> int:
    try:
        start_services()
        return 0
    except Exception as exc:
        print(f"start failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    try:
        stop_services()
        return 0
    except Exception as exc:
        print(f"stop failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    return cmd_start(args)


def build_stats(store) -> dict:
    try:
        from .maintenance import sync_image_files
        counts = sync_image_files(REPO_ROOT)
        non_image_keys = {
            "image_duplicates_removed",
            "missing_cleared",
            "empty_candidate_dirs",
            "resource_links",
            "resource_files",
        }
        images = sum(value for key, value in counts.items() if key not in non_image_keys)
    except Exception as exc:
        print(f"stats image count failed: {type(exc).__name__}: {exc}")
        images = 0
    try:
        links = len(store.recent_link_records(limit=100000))
    except Exception:
        links = 0
    try:
        last_report = store.last_daily_report_sent_at()
        last_report = last_report.isoformat(timespec="seconds") if last_report else None
    except Exception:
        last_report = None
    return {"images": images, "links": links, "lastReport": last_report}


def load_stats() -> dict:
    from .config import load_config
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    return build_stats(store)


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(load_stats(), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"stats failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_status(), ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQ OneBot control bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print run/status.json")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("stats")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "status": cmd_status,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "stats": cmd_stats,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

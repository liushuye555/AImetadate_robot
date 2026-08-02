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
PAUSE_MARKER = RUN_DIR / "collection-paused"
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
            # 注意：不要给 napcat.bat 加引号。subprocess 在 Windows 会把列表参数里的
            # 引号转义成 \"，cmd.exe 会将其解析为带引号的路径导致 "不是内部或外部命令"。
            # 仓库路径不含空格，直接 call 即可。
            ["cmd.exe", "/d", "/s", "/c", f"call {napcat_bat}"],
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
        import sqlite3
        conn = sqlite3.connect(store.path)
        try:
            links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:
        print(f"stats db count failed: {type(exc).__name__}: {exc}")
        links = 0
        images = 0
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


def build_report_preview(store, config=None) -> str:
    from .config import load_config
    from .daily_report import build_daily_resource_report
    config = config or load_config(REPO_ROOT / "config.yaml")
    content = build_daily_resource_report(
        store,
        since=store.last_daily_report_sent_at(),
        include_files=config.daily_report_include_files,
        include_links=config.daily_report_include_links,
        enrich_links=config.daily_report_enrich_links and config.feature_link_metadata,
        analyze_links=config.feature_link_analysis,
        max_links=config.daily_report_max_links,
        max_enriched_links=config.daily_report_max_enriched_links,
        language=config.language,
    )
    return content or "（暂无日报内容）"


def load_report_preview() -> tuple[str, int]:
    from .config import load_config
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    content = build_report_preview(store, config)
    return content, len(content)


def cmd_report_preview(args: argparse.Namespace) -> int:
    try:
        content, chars = load_report_preview()
        print(json.dumps({"ok": True, "content": content, "chars": chars}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


async def _send_report_once() -> int:
    import websockets
    from .config import load_config
    from .daily_report import build_daily_resource_report, split_message
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    content = build_daily_resource_report(
        store,
        since=store.last_daily_report_sent_at(),
        include_files=config.daily_report_include_files,
        include_links=config.daily_report_include_links,
        enrich_links=config.daily_report_enrich_links and config.feature_link_metadata,
        analyze_links=config.feature_link_analysis,
        max_links=config.daily_report_max_links,
        max_enriched_links=config.daily_report_max_enriched_links,
        language=config.language,
    )
    if not content:
        print(json.dumps({"ok": False, "error": "empty report"}, ensure_ascii=False))
        return 1
    async with websockets.connect(config.onebot_ws_url) as ws:
        for chunk in split_message(content, max_chars=1800):
            for user_id in sorted(config.bot.whitelist_users):
                await ws.send(json.dumps(
                    {"action": "send_private_msg",
                     "params": {"user_id": int(user_id), "message": chunk}},
                    ensure_ascii=False,
                ))
    print(json.dumps({"ok": True, "chars": len(content)}, ensure_ascii=False))
    return 0


def cmd_report_send(args: argparse.Namespace) -> int:
    import asyncio
    return asyncio.run(_send_report_once())


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_status(), ensure_ascii=False))
    return 0


def collection_paused() -> bool:
    return PAUSE_MARKER.exists()


def cmd_collection(args: argparse.Namespace) -> int:
    if args.state == "off":
        PAUSE_MARKER.write_text("1", encoding="ascii")
    else:
        PAUSE_MARKER.unlink(missing_ok=True)
    print(json.dumps({"paused": collection_paused()}, ensure_ascii=False))
    return 0


async def _fetch_groups_once() -> list[dict[str, str]]:
    import websockets
    from .config import load_config
    config = load_config(REPO_ROOT / "config.yaml")
    async with websockets.connect(config.onebot_ws_url) as ws:
        echo = f"groups-{datetime.now().timestamp()}"
        await ws.send(
            json.dumps({"action": "get_group_list", "params": {}, "echo": echo}, ensure_ascii=False)
        )
        while True:
            raw = await ws.recv()
            data = json.loads(raw)
            if data.get("echo") == echo:
                rows = data.get("data") or []
                return [
                    {"id": str(item.get("group_id") or ""), "name": str(item.get("group_name") or "")}
                    for item in rows
                    if item.get("group_id")
                ]


def cmd_groups(args: argparse.Namespace) -> int:
    import asyncio
    try:
        groups = asyncio.run(_fetch_groups_once())
        print(json.dumps(groups, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQ OneBot control bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print run/status.json")
    collection_parser = sub.add_parser("collection", help="pause/resume collection")
    collection_parser.add_argument("state", choices=("on", "off"))
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("groups", help="list groups the bot has joined")
    sub.add_parser("stats")
    sub.add_parser("report-preview")
    sub.add_parser("report-send")
    return parser


def main(argv: list[str] | None = None) -> int:
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "status": cmd_status,
        "collection": cmd_collection,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "stats": cmd_stats,
        "report-preview": cmd_report_preview,
        "report-send": cmd_report_send,
        "groups": cmd_groups,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

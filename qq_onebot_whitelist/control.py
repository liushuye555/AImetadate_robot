"""Control bridge used by the Qt panel; keeps operational logic in Python."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .manager_owner import (require_manager, managed_context, process_identity,
                            read_owned_bot, save_bot_owner, is_process_alive,
                            terminate_process_tree, terminate_owned_tree)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "run"
STATUS_PATH = RUN_DIR / "status.json"
PAUSE_MARKER = RUN_DIR / "collection-paused"
NAPCAT_PORT = 6099
ONEBOT_PORT = 3001
STATUS_STALE_SECONDS = 90


def status_path() -> Path:
    return RUN_DIR / "status.json"


def write_status(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    # 每个进程用独立 tmp 名：bot 与面板进程共用固定名会互相覆盖，
    # Windows 上 replace 撞上面板的只读句柄还会抛 PermissionError
    tmp = status_path().with_suffix(f".json.tmp-{os.getpid()}")
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


def manual_stop_path() -> Path:
    return RUN_DIR / "manual-stop"


def manual_stop_requested() -> bool:
    return manual_stop_path().exists()


def _windows_pid_running(pid: int) -> bool:
    """Probe a Windows PID without sending a signal or terminating it."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_running(pid_path: Path) -> bool:
    """Return whether the PID recorded by the manager is still alive."""
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, OSError, ValueError, OverflowError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _windows_pid_running(pid)
        except (OSError, RuntimeError):
            return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False
    return True


def live_status() -> dict:
    """Probe current service liveness without trusting the heartbeat file."""
    try:
        cached = load_status()
    except (OSError, ValueError, json.JSONDecodeError):
        cached = {}
    onebot = port_open(ONEBOT_PORT)
    cached_identity = {}
    try:
        updated_at = datetime.fromisoformat(str(cached.get("updatedAt") or "").replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.astimezone()
        age = (datetime.now().astimezone() - updated_at.astimezone()).total_seconds()
        if 0 <= age <= STATUS_STALE_SECONDS:
            cached_identity = cached
    except (TypeError, ValueError, OverflowError):
        pass
    return {
        "napcat": port_open(NAPCAT_PORT),
        "onebot": onebot,
        "bot": owned_bot_running(),
        # NapCat exposes OneBot only after QQ login; this is the same liveness
        # contract used by status_writer_loop.
        "qqLoggedIn": onebot,
        "qqNumber": str(cached_identity.get("qqNumber") or "") if onebot else "",
        "qqNickname": str(cached_identity.get("qqNickname") or "") if onebot else "",
        "collectionPaused": collection_paused(),
        "manualStop": manual_stop_requested(),
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def owned_bot_running() -> bool:
    """Prefer exact managed identities, including when probing outside the Job."""
    if not (RUN_DIR / 'bot-owner.json').exists():
        return pid_running(RUN_DIR / 'bot.pid')  # Legacy migration only.
    try:
        owner = json.loads((RUN_DIR / 'manager-session.json').read_text(encoding='utf-8'))
        return (isinstance(owner, dict)
                and is_process_alive(owner.get('pid'), owner.get('created'))
                and read_owned_bot(REPO_ROOT, owner.get('session')) is not None)
    except (OSError, ValueError, TypeError):
        return False


def request_manager(action: str = 'show') -> int:
    """External commands go through the single Qt owner; never launch a bare bot."""
    executable = REPO_ROOT / 'qq-onebot-manager-qt' / 'build' / 'qq-onebot-manager-qt.exe'
    if not executable.is_file():
        raise RuntimeError('管理器尚未构建，请先构建并启动 Qt 管理器。')
    arguments = [str(executable)]
    if action != 'show':
        arguments.append('--' + action)
    subprocess.Popen(arguments, cwd=str(REPO_ROOT), close_fds=True,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return 0


def _retire_legacy_bots() -> None:
    """One-time migration: terminate only verified project bot command lines."""
    import re
    candidates = set()
    for path in (RUN_DIR / 'bot.pid', REPO_ROOT / 'data' / 'bot.lock'):
        try:
            value = int(path.read_text(encoding='ascii').strip())
            if value > 0:
                candidates.add(value)
        except (OSError, ValueError):
            pass
    for pid in candidates:
        created = process_identity(pid)
        if created is None:
            continue
        probe = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
        try:
            command = json.loads(probe.stdout)
        except (ValueError, TypeError):
            command = ''
        if not isinstance(command, str) or not re.search(r'(?<![\w.])qq_onebot_whitelist[.]onebot(?![\w.])', command):
            raise RuntimeError('旧进程记录不属于本项目机器人，已拒绝终止；请检查 run/bot.pid。')
        config_arg = re.search(r'--config(?:=|\s+)(?:"([^"]+)"|(\S+))', command)
        if config_arg is None:
            raise RuntimeError('旧机器人缺少可核对的配置路径，已拒绝接管。')
        try:
            same_project = os.path.samefile(config_arg.group(1) or config_arg.group(2), REPO_ROOT / 'config.yaml')
        except OSError:
            same_project = False
        if not same_project or process_identity(pid) != created:
            raise RuntimeError('旧机器人进程身份不匹配，已拒绝终止。')
        if not terminate_process_tree(pid, created):
            raise RuntimeError('旧机器人未能停止，未启动第二个实例。')


def start_services(*, clear_manual_stop: bool = False) -> int:
    """Start the bot only inside the manager's Job; NapCat explicitly stays outside."""
    session = require_manager(REPO_ROOT)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    existing = read_owned_bot(REPO_ROOT, session['session'])
    if existing is not None:
        if clear_manual_stop:
            manual_stop_path().unlink(missing_ok=True)
        return existing
    _retire_legacy_bots()
    napcat_dir = REPO_ROOT / 'runtime' / 'NapCat.Shell.Windows.Node'
    napcat_bat = napcat_dir / 'napcat.bat'
    config = REPO_ROOT / 'config.yaml'
    python = REPO_ROOT / '.venv' / 'Scripts' / 'python.exe'
    if not config.is_file() or not python.is_file():
        raise RuntimeError('缺少项目配置或 Python 运行环境，无法启动托管后台。')
    if not port_open(NAPCAT_PORT):
        if not napcat_bat.is_file():
            raise RuntimeError('NapCat 启动文件不存在。')
        with (REPO_ROOT / 'logs' / 'napcat.log').open('a', encoding='utf-8', errors='replace') as output:
            process = subprocess.Popen(['cmd.exe', '/d', '/s', '/c', f'call {napcat_bat}'],
                cwd=str(napcat_dir), stdout=output, stderr=subprocess.STDOUT, close_fds=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0x01000000))
        (RUN_DIR / 'napcat.pid').write_text(str(process.pid), encoding='ascii')
    # The bot already retries OneBot connection; do not block manager startup on QQ login.
    require_manager(REPO_ROOT)
    with (REPO_ROOT / 'logs' / 'bot.log').open('a', encoding='utf-8', errors='replace') as output:
        process = subprocess.Popen([str(python), '-u', '-m', 'qq_onebot_whitelist.onebot', '--config', str(config)],
            cwd=str(REPO_ROOT), stdout=output, stderr=subprocess.STDOUT, close_fds=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    save_bot_owner(REPO_ROOT, process.pid, session['session'])
    (RUN_DIR / 'bot.pid').write_text(str(process.pid), encoding='ascii')
    if clear_manual_stop:
        manual_stop_path().unlink(missing_ok=True)
    return process.pid


def cmd_start(args: argparse.Namespace) -> int:
    try:
        if not managed_context(REPO_ROOT):
            return request_manager()
        pid = start_services(clear_manual_stop=True)
        print(json.dumps({'status': 'running', 'pid': pid}))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    try:
        return request_manager('stop-services')
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


def cmd_restart(args: argparse.Namespace) -> int:
    return cmd_bot_restart(args)


def cmd_bot_restart(args: argparse.Namespace) -> int:
    if manual_stop_requested():
        return 0
    try:
        if not managed_context(REPO_ROOT):
            return request_manager('restart-services')
        session = require_manager(REPO_ROOT)
        pid = read_owned_bot(REPO_ROOT, session['session'])
        if pid is not None:
            if not terminate_owned_tree(REPO_ROOT, session['session']):
                raise RuntimeError('旧后台未能停止，未重复启动。')
        (RUN_DIR / 'bot.pid').unlink(missing_ok=True)
        result = start_services()
        print(json.dumps({'status': 'running', 'pid': result}))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


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


def cmd_live_status(args: argparse.Namespace) -> int:
    print(json.dumps(live_status(), ensure_ascii=False))
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


def cmd_custom(args: argparse.Namespace) -> int:
    """查看自定义采集记录（按规则可选）。"""
    try:
        from .config import load_config
        from .store import Store
        config = load_config(REPO_ROOT / "config.yaml")
        store = Store(config.data_dir / "bot.db")
        rows = store.recent_custom_collections(rule=args.rule or None, limit=50)
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def cmd_vision_recheck(args: argparse.Namespace) -> int:
    """手动跑一批 DeepSeek 视觉复核（force=True 绕过错峰窗口限制）。"""
    try:
        from .config import load_config
        from .vision_recheck import recheck_batch
        result = recheck_batch(REPO_ROOT, load_config(REPO_ROOT / 'config.yaml'),
                               limit=max(1, int(args.limit)), force=not args.respect_window)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def cmd_view(args: argparse.Namespace) -> int:
    """重新生成报告视图（含资源/文件页），并输出分类列表。

    负载感知：启用负载调度且 CPU 超过阈值时，不重建视图，
    直接返回现有分类统计并标注 deferred=true。
    """
    try:
        from .config import load_config
        from .load_aware import load_aware_ok
        config = load_config(REPO_ROOT / 'config.yaml')
        if not load_aware_ok(config):
            from .build_image_view import stale_view_counts
            counts = stale_view_counts(REPO_ROOT / 'data' / 'view')
            print(json.dumps({"categories": [
                {"name": name, "count": count, "url": name + "/index.html"}
                for name, count in sorted(counts.items())
            ], "deferred": True}, ensure_ascii=False))
            return 0
        from .maintenance import sync_image_files
        counts = sync_image_files(REPO_ROOT)
        from .knowledge import write_view as write_knowledge_view
        write_knowledge_view(config.data_dir, config)
        categories = []
        for name, count in sorted(counts.items()):
            if name.startswith(('image_', 'missing_', 'candidates_', 'obfuscation_', 'empty_', 'resource_', 'archive_')):
                continue
            categories.append({"name": name, "count": count, "url": name + "/index.html"})
        print(json.dumps({"categories": categories, "deferred": False}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def cmd_view_list(args: argparse.Namespace) -> int:
    """快速列出现有报告分类（不重建视图）。"""
    try:
        from .build_image_view import ALL_GALLERY_DIR, CATEGORY_NAMES
        from .resource_view import RESOURCE_CHUNKS_DIR
        view = REPO_ROOT / "data" / "view"
        categories = []
        if view.exists():
            exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
            for p in sorted(view.iterdir()):
                if not p.is_dir() or p.name == RESOURCE_CHUNKS_DIR:
                    continue
                count = sum(1 for f in p.rglob("*") if f.is_file() and f.suffix.lower() in exts)
                categories.append({"name": p.name, "count": count, "url": p.name + "/index.html"})
        # 合并图库不含候选暂存区；快速列表与实际页面保持相同范围。
        total = sum(c["count"] for c in categories
                    if c["name"] not in (ALL_GALLERY_DIR, CATEGORY_NAMES['candidate']))
        for c in categories:
            if c["name"] == ALL_GALLERY_DIR:
                c["count"] = total
        print(json.dumps({"categories": categories}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def cmd_backup(args: argparse.Namespace) -> int:
    """执行一次备份（DB 快照 + config 归档，可选图片镜像），结果写入 run/backup-state.json。"""
    try:
        from . import backup
        from .config import load_config
        config = load_config(REPO_ROOT / "config.yaml")
        if getattr(args, "pre", None):
            snapshot = backup.pre_operation_snapshot(
                config.data_dir / "bot.db", config.backup_dir, args.pre
            )
            print(json.dumps({"ok": True, "file": snapshot.name}, ensure_ascii=False))
            return 0
        if not config.backup_enabled:
            print(json.dumps({"ok": False, "error": "backup.enabled=false"}, ensure_ascii=False))
            return 1
        result = backup.run_backup(
            config.data_dir / "bot.db",
            config.backup_dir,
            keep_daily=config.backup_keep_daily,
            keep_weekly=config.backup_keep_weekly,
            min_free_mb=config.backup_min_free_mb,
            config_yaml=REPO_ROOT / "config.yaml",
            images_source=(config.data_dir / "images") if config.backup_images else None,
            images_target=config.backup_images_dir if config.backup_images else None,
            force_kind=getattr(args, "kind", None),
        )
        print(json.dumps({"ok": result.get("backupOk", False), **result}, ensure_ascii=False))
        return 0 if result.get("backupOk") else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


async def _file_sync_scan(config) -> dict:
    """开一条短 ws 连接，扫描目标群文件树并入队（补历史）。"""
    import asyncio
    import websockets

    from . import file_sync
    from .store import Store

    store = Store(config.data_dir / "bot.db")
    enqueued = 0
    per_group: dict = {}
    async with websockets.connect(config.onebot_ws_url) as ws:

        async def call_action(action: str, params: dict) -> dict:
            echo = f"fs-{action}-{time.time()}"
            await ws.send(json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False))
            deadline = time.monotonic() + 30
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{action} 超时")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                data = json.loads(raw)
                if data.get("echo") != echo:
                    continue
                if isinstance(data.get("status"), str) and data["status"].lower() in ("failed", "false"):
                    raise RuntimeError(f"{action} 失败: {data.get('message') or data.get('wording')}")
                return data

        group_ids = set(config.file_sync_groups)
        if not group_ids:
            listing = await call_action("get_group_list", {})
            rows = listing.get("data") or []
            group_ids = {str(item.get("group_id")) for item in rows if item.get("group_id")} - config.blocked_groups
        for group_id in sorted(group_ids):
            count_new = 0

            def on_file(row, gid=group_id):
                nonlocal count_new
                if store.enqueue_file_upload(
                    scope=gid,
                    file_id=row["file_id"],
                    file_name=row["file_name"],
                    file_size=row.get("file_size"),
                    upload_time=str(row.get("upload_time")) if row.get("upload_time") is not None else None,
                    busid=row.get("busid"),
                ):
                    count_new += 1

            try:
                total = await file_sync.scan_group(call_action, group_id, on_file=on_file)
                per_group[group_id] = {"total": total, "new": count_new}
                enqueued += count_new
            except Exception as exc:
                per_group[group_id] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"groups": per_group, "enqueued": enqueued}


def cmd_file_sync(args: argparse.Namespace) -> int:
    try:
        from . import file_sync
        from .config import load_config
        from .store import Store
        config = load_config(REPO_ROOT / "config.yaml")
        if args.retry_failed:
            store = Store(config.data_dir / "bot.db")
            n = store.retry_failed_file_uploads()
            print(json.dumps({"ok": True, "retried": n}, ensure_ascii=False))
            return 0
        if args.scan:
            import asyncio
            result = asyncio.run(_file_sync_scan(config))
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.run:
            if not config.file_sync_enabled:
                print(json.dumps({"ok": False, "error": "file_sync.enabled=false"}, ensure_ascii=False))
                return 1
            import asyncio
            from .store import Store

            store = Store(config.data_dir / "bot.db")

            async def _run():
                def fetch_url(group_id, file_id, busid=None):
                    return asyncio.to_thread(
                        file_sync.fetch_download_url_once, group_id, file_id, busid,
                        ws_url=config.onebot_ws_url,
                    )
                return await file_sync.process_pending(store, config, fetch_url, limit=int(args.run))

            stats = asyncio.run(_run())
            print(json.dumps({"ok": True, **stats}, ensure_ascii=False))
            return 0
        store = Store(config.data_dir / "bot.db")
        print(json.dumps({
            "ok": True,
            "enabled": config.file_sync_enabled,
            "webdav": config.file_sync_webdav_url,
            "remoteDir": config.file_sync_remote_dir,
            "status": store.file_upload_status_counts(),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQ OneBot control bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print run/status.json")
    sub.add_parser("live-status", help="probe current service liveness")
    collection_parser = sub.add_parser("collection", help="pause/resume collection")
    collection_parser.add_argument("state", choices=("on", "off"))
    custom_parser = sub.add_parser("custom", help="inspect custom collection records")
    custom_parser.add_argument("--rule", default=None, help="filter by rule name")
    sub.add_parser("view", help="rebuild report views")
    vision = sub.add_parser("vision-recheck", help="visually recheck misclassified 02/03 images")
    vision.add_argument("--limit", default="20")
    vision.add_argument("--respect-window", action="store_true")
    sub.add_parser("view-list", help="list existing report categories")
    backup_parser = sub.add_parser("backup", help="run a backup now (DB snapshot + config)")
    backup_parser.add_argument("--pre", default=None, metavar="REASON",
                               help="dangerous-op snapshot: bot-pre-<reason>-<ts>.db, exempt from retention")
    backup_parser.add_argument("--kind", default=None, choices=("daily", "weekly"),
                               help="force snapshot kind instead of weekday-based")
    file_sync_parser = sub.add_parser("file-sync", help="group file cloud sync status/scan/run")
    file_sync_parser.add_argument("--scan", action="store_true",
                                  help="list all group files via NapCat and enqueue (backfill)")
    file_sync_parser.add_argument("--run", nargs="?", const=3, default=None, metavar="N",
                                  help="process up to N pending files now")
    file_sync_parser.add_argument("--retry-failed", action="store_true",
                                  help="requeue failed uploads")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("bot-restart")
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
        "live-status": cmd_live_status,
        "collection": cmd_collection,
        "custom": cmd_custom,
        "view": cmd_view,
        "vision-recheck": cmd_vision_recheck,
        "view-list": cmd_view_list,
        "backup": cmd_backup,
        "file-sync": cmd_file_sync,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "bot-restart": cmd_bot_restart,
        "stats": cmd_stats,
        "report-preview": cmd_report_preview,
        "report-send": cmd_report_send,
        "groups": cmd_groups,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any

import websockets

from .archive_budget import enforce_archive_budget
from .collection import (
    ai_match_and_collect,
    collect_event,
    collection_allows,
    forward_ids,
    is_collection_paused,
    is_forward_event,
)
from .commands import build_reply, scope_for_event
from .config import AppConfig, load_config
from .ai_context_analyze import analyze_configured, configured_scopes
from .daily_report import build_daily_resource_report, should_run_daily_report, split_message, today_key
from .maintenance import sync_image_files
from .policy import extract_text, should_reply
from .schedule import is_in_time_windows
from .store import Store


_echo_state: dict[tuple[str, str], list[float]] = {}
_group_activity: dict[str, float] = {}


def echo_reply_text(event: dict[str, Any], config: AppConfig) -> str | None:
    """多人重复同一条消息时返回要复读的文本；未触发返回 None。"""
    if not config.echo_enabled or event.get('post_type') != 'message' or event.get('message_type') != 'group':
        return None
    group = str(event.get('group_id') or '')
    if not group:
        return None
    if config.echo_groups and group not in config.echo_groups:
        return None
    text = extract_text(event).strip()
    if not text or len(text) > 100:
        return None
    now = time.time()
    key = (group, text)
    stamps = _echo_state.setdefault(key, [])
    stamps.append(now)
    cutoff = now - max(1, config.echo_window_seconds)
    _echo_state[key] = [item for item in stamps if item >= cutoff]
    if len(_echo_state[key]) >= max(2, config.echo_min_repeat):
        _echo_state.pop(key, None)
        return text
    return None


def system_cpu_percent() -> float:
    """通过 GetSystemTimes 采样 CPU 占用（0~100），失败时返回 0。"""
    try:
        import ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        def sample():
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            return idle, kernel, user

        def to64(ft: FILETIME) -> int:
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        idle1, kernel1, user1 = sample()
        time.sleep(0.4)
        idle2, kernel2, user2 = sample()
        idle = to64(idle2) - to64(idle1)
        total = (to64(kernel2) - to64(kernel1)) + (to64(user2) - to64(user1))
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - idle / total)))
    except Exception:
        return 0.0


async def call_action(ws, action: str, params: dict[str, Any]) -> dict[str, Any]:
    echo = f'startup-{action}-{datetime.now().timestamp()}'
    await ws.send(json.dumps({'action': action, 'params': params, 'echo': echo}, ensure_ascii=False))
    while True:
        raw = await ws.recv()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if data.get('echo') == echo:
            return data


async def startup_history_groups(ws, config: AppConfig) -> list[str]:
    if config.startup_history_mode == 'blacklist':
        resp = await call_action(ws, 'get_group_list', {})
        groups = (resp.get('data') or [])
        ids = []
        for item in groups:
            gid = str(item.get('group_id') or '')
            if gid and gid not in config.blocked_groups:
                ids.append(gid)
        return ids
    return sorted(config.startup_history_groups)


async def startup_history_catchup(ws, config: AppConfig, store: Store) -> None:
    if not config.startup_history_enabled or not config.feature_startup_history:
        return
    groups = await startup_history_groups(ws, config)
    if not groups:
        return
    total = 0
    for group_id in groups:
        cursor = store.get_history_cursor(group_id)
        known_newest = str(cursor.get('newest_seq')) if cursor and cursor.get('newest_seq') else None
        seq = 0
        seen: set[str] = set()
        newest_seen: str | None = None
        oldest_seen: str | None = None
        reached_known = False
        page_limit = config.startup_history_max_pages if config.startup_history_all else config.startup_history_pages
        for page in range(max(1, page_limit)):
            params = {
                'group_id': int(group_id),
                'count': config.startup_history_count,
                'message_seq': seq,
                'reverse_order': page > 0,
            }
            resp = await call_action(ws, 'get_group_msg_history', params)
            messages = ((resp.get('data') or {}).get('messages') or [])
            if not messages:
                break
            next_seq = messages[0].get('message_seq') or seq
            for msg in messages:
                msg_seq = str(msg.get('message_seq') or msg.get('message_id') or '')
                if known_newest and not config.startup_history_all and msg_seq == known_newest:
                    reached_known = True
                    break
                if msg_seq and msg_seq in seen:
                    continue
                if msg_seq:
                    seen.add(msg_seq)
                    if newest_seen is None:
                        newest_seen = msg_seq
                if not is_blocked_event(msg, config):
                    record_event(store, msg, config)
                    total += 1
            if next_seq:
                oldest_seen = str(next_seq)
            if reached_known or not next_seq or next_seq == seq:
                break
            seq = next_seq
        if newest_seen or oldest_seen:
            store.update_history_cursor(group_id, newest_seq=newest_seen, oldest_seq=oldest_seen)
    print(f'startup history catch-up imported {total} messages')


async def send_reply(ws, event: dict[str, Any], text: str) -> None:
    if event.get('message_type') == 'group':
        action = 'send_group_msg'
        target = event.get('group_id')
        params = {'group_id': target, 'message': text}
    else:
        action = 'send_private_msg'
        target = event.get('user_id')
        params = {'user_id': target, 'message': text}
    print(f'reply_send action={action} target={target} chars={len(text)} text={text[:40]!r}')
    await ws.send(json.dumps({'action': action, 'params': params}, ensure_ascii=False))


async def send_private(ws, user_id: str, text: str) -> None:
    await ws.send(json.dumps({'action': 'send_private_msg', 'params': {'user_id': user_id, 'message': text}}, ensure_ascii=False))


async def _fetch_group_ids(ws, config: AppConfig) -> set[str]:
    """通过独立连接获取机器人所在群列表。"""
    try:
        async with websockets.connect(config.onebot_ws_url) as action_ws:
            echo = f"groups-{datetime.now().timestamp()}"
            await action_ws.send(
                json.dumps({"action": "get_group_list", "params": {}, "echo": echo}, ensure_ascii=False)
            )
            while True:
                raw = await asyncio.wait_for(action_ws.recv(), timeout=8)
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                if data.get("echo") == echo:
                    rows = data.get("data") or []
                    return {str(item.get("group_id")) for item in rows if item.get("group_id")}
    except Exception as exc:
        print(f"fetch group list failed: {type(exc).__name__}: {exc}")
    return set()


async def keepalive_targets(ws, config: AppConfig) -> set[str]:
    """按保活群范围模式计算目标群：all/whitelist/blacklist/custom。"""
    if config.keepalive_mode == 'whitelist':
        return {str(g) for g in config.bot.whitelist_groups}
    if config.keepalive_mode == 'custom':
        return {str(g) for g in config.keepalive_groups}
    groups = await _fetch_group_ids(ws, config)
    return groups - config.blocked_groups


async def _send_group_message(ws, group_id: str, message: str) -> None:
    await ws.send(json.dumps(
        {'action': 'send_group_msg', 'params': {'group_id': int(group_id), 'message': message}},
        ensure_ascii=False,
    ))


def contains_at_all(event: dict[str, Any]) -> bool:
    """检测群消息是否 @全体成员（管理员清理前常发的公告）。"""
    for segment in (event.get('message') or []):
        if not isinstance(segment, dict):
            continue
        if segment.get('type') == 'at':
            data = segment.get('data') or {}
            if str(data.get('qq') or '') in ('all', '0', '全体成员'):
                return True
        data = segment.get('data')
        if isinstance(data, dict):
            text = str(data.get('text') or '')
            if '全体成员' in text or '@all' in text.lower():
                return True
    return False


async def keepalive_loop(ws, config: AppConfig) -> None:
    last_timed = 0.0
    while True:
        try:
            now = time.time()
            if config.keepalive_enabled and config.keepalive_message.strip():
                targets = await keepalive_targets(ws, config)
                # 定时保活
                if config.keepalive_interval_minutes > 0 and now - last_timed >= config.keepalive_interval_minutes * 60:
                    for group_id in sorted(targets):
                        await _send_group_message(ws, group_id, config.keepalive_message)
                        _group_activity[group_id] = time.time()
                    last_timed = now
                # 触发保活：群空闲超过阈值自动保活
                if config.keepalive_trigger_enabled and config.keepalive_idle_minutes > 0:
                    idle_limit = config.keepalive_idle_minutes * 60
                    for group_id in sorted(targets):
                        last = _group_activity.get(group_id)
                        if last is None:
                            _group_activity[group_id] = now  # 首次见到该群，先记基线
                        elif now - last >= idle_limit:
                            await _send_group_message(ws, group_id, config.keepalive_message)
                            _group_activity[group_id] = time.time()
        except Exception as exc:
            print(f'keepalive_loop failed: {type(exc).__name__}: {exc}')
        await asyncio.sleep(30)


async def status_writer_loop(ws, config: AppConfig, login_info: dict[str, Any] | None = None) -> None:
    from . import control
    login = login_info or {"qqLoggedIn": False, "qqNumber": "", "qqNickname": ""}
    while True:
        try:
            control.write_status(
                {
                    "napcat": control.port_open(control.NAPCAT_PORT),
                    # 主连接活着即 OneBot 在线、QQ 已登录（端口 3001 只在 QQ 登录后开放）
                    "onebot": True,
                    "bot": True,
                    "collectionPaused": is_collection_paused(),
                    **login,
                }
            )
        except Exception as exc:
            print(f"status_writer failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(30)


def should_run_ai_context(config_path: str | Path, store: Store, now: datetime) -> tuple[bool, int, AppConfig]:
    current = load_config(config_path)
    scopes = [scope for scope in configured_scopes(current, current.data_dir / 'bot.db') if scope]
    pending = sum(
        store.count_messages_after(str(scope), store.last_ai_context_end_message_id(str(scope)))
        for scope in scopes
    )
    allowed = is_in_time_windows(now, current.ai_context_allowed_windows)
    enabled = current.ai_context_enabled and current.feature_ai_context
    return enabled and pending >= current.ai_context_min_new_messages and allowed, pending, current


def ai_retry_delay_seconds(failures: int) -> int:
    return min(3600, 900 * (2 ** max(0, int(failures) - 1)))


async def ai_context_loop(config_path: str | Path, store: Store) -> None:
    running = False
    current = None
    failure_count = 0
    retry_after: datetime | None = None
    while True:
        try:
            now = datetime.now()
            if retry_after and now < retry_after:
                await asyncio.sleep(max(1, int((retry_after - now).total_seconds())))
                continue
            should_run, pending, current = should_run_ai_context(config_path, store, datetime.now())
            if should_run and not running:
                if current.load_aware_enabled:
                    cpu = await asyncio.to_thread(system_cpu_percent)
                    if cpu >= current.load_aware_cpu_threshold:
                        delay = max(1, current.load_aware_check_seconds)
                        print(f'load_aware: CPU {cpu:.0f}% >= {current.load_aware_cpu_threshold}%，推迟 AI 分析 {delay}s')
                        retry_after = datetime.now() + timedelta(seconds=delay)
                        await asyncio.sleep(5)
                        continue
                running = True
                try:
                    print(f'ai_context auto run starting, pending messages={pending}')
                    await asyncio.to_thread(analyze_configured, str(config_path))
                    print('ai_context auto run finished')
                    failure_count = 0
                    retry_after = None
                finally:
                    running = False
            elif pending >= current.ai_context_min_new_messages:
                print(f'ai_context waiting for allowed window, pending messages={pending}, windows={current.ai_context_allowed_windows}')
        except Exception as exc:
            failure_count += 1
            delay = ai_retry_delay_seconds(failure_count)
            retry_after = datetime.now() + timedelta(seconds=delay)
            print(f'ai_context_loop failed: {type(exc).__name__}: {exc}; retry_in={delay}s')
        await asyncio.sleep(max(1, current.ai_context_auto_interval_minutes if current else 1) * 60)


async def daily_report_loop(ws, config: AppConfig, store: Store) -> None:
    while True:
        now = datetime.now()
        key = today_key(now)
        try:
            if config.daily_report_enabled and config.feature_daily_report and should_run_daily_report(hour=now.hour, target_hour=config.daily_report_hour, already_sent=store.has_daily_report(key)):
                since = store.last_daily_report_sent_at()
                content = await asyncio.to_thread(
                    build_daily_resource_report, store, since=since,
                    include_files=config.daily_report_include_files,
                    include_links=config.daily_report_include_links,
                    enrich_links=config.daily_report_enrich_links and config.feature_link_metadata,
                    analyze_links=config.feature_link_analysis,
                    max_links=config.daily_report_max_links,
                    max_enriched_links=config.daily_report_max_enriched_links,
                    language=config.language,
                )
                if content:
                    chunks = split_message(content, max_chars=1800)
                    for user_id in sorted(config.bot.whitelist_users):
                        for idx, chunk in enumerate(chunks, 1):
                            prefix = (f'{"资源日报" if config.language == "zh-CN" else "Daily resource report"} {idx}/{len(chunks)}\n' if len(chunks) > 1 else '')
                            await send_private(ws, user_id, prefix + chunk)
                    print(f'daily_report sent to {sorted(config.bot.whitelist_users)} chunks={len(chunks)} chars={len(content)}')
                    store.mark_daily_report_sent(key, content)
        except Exception as exc:
            print(f'daily_report_loop failed: {type(exc).__name__}: {exc}')
        await asyncio.sleep(300)


def record_event(store: Store, event: dict[str, Any], config: AppConfig) -> None:
    """采集委托：完整流水线在 collection.collect_event。"""
    collect_event(store, event, config)


async def collect_forward_contents(store: Store, event: dict[str, Any], config: AppConfig) -> None:
    """展开转发的合并消息：抓取实际内容并逐条采集（后台任务，不阻塞消息循环）。"""
    scope = scope_for_event(event)
    if not collection_allows(scope, 'forwards', config):
        return
    ids = forward_ids(event)
    if not ids:
        return
    try:
        async with websockets.connect(config.onebot_ws_url) as action_ws:
            for fid in ids:
                echo = f"fwd-{fid}-{datetime.now().timestamp()}"
                await action_ws.send(
                    json.dumps({"action": "get_forward_msg", "params": {"id": fid}, "echo": echo}, ensure_ascii=False)
                )
                while True:
                    raw = await asyncio.wait_for(action_ws.recv(), timeout=10)
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    if data.get("echo") == echo:
                        messages = ((data.get("data") or {}).get("messages") or [])
                        for sub in messages:
                            sub_event = {
                                "post_type": "message",
                                "message_type": "group",
                                "group_id": event.get("group_id"),
                                "user_id": sub.get("user_id") or "",
                                "message": sub.get("message") or [],
                            }
                            collect_event(store, sub_event, config)
                        break
    except Exception as exc:
        print(f"expand forward failed: {type(exc).__name__}: {exc}")


def is_blocked_event(event: dict[str, Any], config: AppConfig) -> bool:
    return event.get('message_type') == 'group' and str(event.get('group_id') or '') in config.blocked_groups


async def handle_event(ws, event: dict[str, Any], config: AppConfig, store: Store, config_path: str | Path = 'config.yaml') -> bool:
    if event.get('post_type') != 'message':
        return False
    if event.get('message_type') == 'group':
        _group_activity[str(event.get('group_id') or '')] = time.time()
        if config.keepalive_enabled and config.keepalive_message.strip() and contains_at_all(event):
            # 管理员 @全体成员（常伴随清理死人）→ 立即发保活消息，避免机器人被当不活跃账号清理
            await _send_group_message(ws, str(event.get('group_id') or ''), config.keepalive_message)
            _group_activity[str(event.get('group_id') or '')] = time.time()
    if is_blocked_event(event, config):
        return False
    echo_text = echo_reply_text(event, config)
    if echo_text is not None:
        await send_reply(ws, event, echo_text)
        return True
    record_event(store, event, config)
    if config.collection_expand_forwards and is_forward_event(event):
        asyncio.create_task(collect_forward_contents(store, event, config))
    if any(rule.get('ai_match') for rule in config.collection_rules):
        asyncio.create_task(asyncio.to_thread(ai_match_and_collect, store, event, extract_text(event), config))
    if not should_reply(event, config.bot):
        return False
    reply = build_reply(
        event,
        store,
        default_summary_limit=config.default_summary_limit,
        max_summary_limit=config.max_summary_limit,
        view_builder=lambda: sync_image_files(Path.cwd()),
        config_path=config_path,
        language=config.language,
    )
    await send_reply(ws, event, reply)
    return True


async def startup_history_catchup_worker(config: AppConfig, store: Store) -> None:
    try:
        async with websockets.connect(config.onebot_ws_url) as action_ws:
            await startup_history_catchup(action_ws, config, store)
        counts = sync_image_files(Path.cwd())
        print('image view refreshed after startup catch-up: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    except Exception as exc:
        print(f'startup history catch-up failed: {type(exc).__name__}: {exc}')


async def run(config: AppConfig, config_path: str | Path = 'config.yaml') -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / 'bot.db')
    try:
        counts = sync_image_files(Path.cwd())
        print('image view refreshed on startup: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    except Exception as exc:
        print(f'image view refresh failed on startup: {type(exc).__name__}: {exc}')
    async with websockets.connect(config.onebot_ws_url) as ws:
        login_info = {}
        try:
            resp = await call_action(ws, "get_login_info", {})
            data = resp.get("data") or {}
            qq_number = str(data.get("user_id") or "")
            login_info = {
                "qqLoggedIn": bool(qq_number),
                "qqNumber": qq_number,
                "qqNickname": str(data.get("nickname") or ""),
            }
        except Exception as exc:
            print(f"get_login_info failed at startup: {type(exc).__name__}: {exc}")
        startup_task = asyncio.create_task(startup_history_catchup_worker(config, store))
        report_task = asyncio.create_task(daily_report_loop(ws, config, store))
        ai_task = asyncio.create_task(ai_context_loop(config_path, store))
        keepalive_task = asyncio.create_task(keepalive_loop(ws, config))
        status_task = asyncio.create_task(status_writer_loop(ws, config, login_info))
        try:
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                try:
                    await handle_event(ws, event, config, store, config_path)
                except Exception as exc:
                    print(f'handle_event failed: {type(exc).__name__}: {exc}')
        finally:
            startup_task.cancel()
            report_task.cancel()
            ai_task.cancel()
            keepalive_task.cancel()
            status_task.cancel()
            from . import control
            control.write_status(
                {"napcat": control.port_open(control.NAPCAT_PORT),
                 "onebot": False, "bot": True,
                 "qqLoggedIn": False, "qqNumber": "", "qqNickname": ""}
            )


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='OneBot whitelist @ bot')
    parser.add_argument('--config', default='config.yaml')
    args = parser.parse_args()
    asyncio.run(run(load_config(args.config), args.config))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

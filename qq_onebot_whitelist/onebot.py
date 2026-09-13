from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
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
from .commands import build_reply, parse_repair_images_command, scope_for_event
from .config import AppConfig, load_config
from .ai_context_analyze import analyze_configured, configured_scopes
from .daily_report import build_daily_resource_report, should_run_daily_report, split_message, today_key
from .maintenance import sync_image_files
from .load_aware import load_aware_defer_seconds, load_aware_ok, system_cpu_percent


_REPO_ROOT = Path(__file__).resolve().parents[1]
_sync_requested = threading.Event()


def request_image_sync() -> None:
    """请求后台负载感知同步重建视图（面板/回复触发）。"""
    _sync_requested.set()
from .policy import extract_text, is_group_admin, should_reply
from .schedule import all_day_today, is_in_time_windows
from .store import Store


_echo_state: dict[tuple[str, str], list[tuple[str, float]]] = {}
_echo_last: dict[str, tuple[str, float]] = {}
_group_activity: dict[str, float] = {}
_purge_keepalive_last: dict[str, float] = {}
PURGE_KEEPALIVE_COOLDOWN_SECONDS = 60


def _is_self_message(event: dict[str, Any]) -> bool:
    """Return true only when both OneBot IDs are present and equal."""
    user_id = str(event.get("user_id") or "")
    self_id = str(event.get("self_id") or "")
    return bool(user_id and self_id and user_id == self_id)


def echo_reply_text(event: dict[str, Any], config: AppConfig) -> str | None:
    """多人连续重复同一条消息时返回要复读的文本；window_seconds=0 表示无限（只看连续性）。"""
    if _is_self_message(event):
        return None
    if not config.echo_enabled or event.get('post_type') != 'message' or event.get('message_type') != 'group':
        return None
    group = str(event.get('group_id') or '')
    sender = str(event.get('user_id') or '')
    if not group or not sender:
        return None
    if config.echo_groups and group not in config.echo_groups:
        return None
    text = extract_text(event).strip()
    if not text or len(text) > 100:
        return None
    now = time.time()
    window = max(0, config.echo_window_seconds)
    key = (group, text)
    # 连续性：本群上一条是不同文本 → 重置该文本的计数
    last = _echo_last.get(group)
    if last and last[0] != text:
        _echo_state.pop((group, last[0]), None)
    _echo_last[group] = (text, now)
    senders = _echo_state.setdefault(key, [])
    if window > 0:
        cutoff = now - window
        senders[:] = [item for item in senders if item[1] >= cutoff]
    for index, (known_sender, _) in enumerate(senders):
        if known_sender == sender:
            senders[index] = (sender, now)
            break
    else:
        senders.append((sender, now))
    if len(senders) >= max(2, config.echo_min_repeat):
        _echo_state.pop(key, None)
        return text
    return None


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
    print(f'reply_send action={action} target={target} chars={len(text)} text={ascii(text[:40])}')
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


PURGE_KEYWORDS = ('清理', '死人', '不活跃', '移除', '踢出', '踢人', '长期未发言', '活跃')


def is_purge_announcement(event: dict[str, Any]) -> bool:
    """判断是否“清理不活跃成员”类公告：@全体成员 且 内容含清理相关关键词。"""
    if not contains_at_all(event):
        return False
    text = extract_text(event).lower()
    return any(keyword in text for keyword in PURGE_KEYWORDS)


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
                    "manualStop": control.manual_stop_requested(),
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
    # DeepSeek 错峰政策支持按星期全天放开（如周末全天错峰），其余时间按窗口判定
    allowed = all_day_today(current.ai_context_all_day_weekdays, now) or         is_in_time_windows(now, current.ai_context_allowed_windows)
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
                cpu = await asyncio.to_thread(system_cpu_percent)
                if not load_aware_ok(current, cpu):
                    delay = load_aware_defer_seconds(current)
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


async def image_worker_loop(config: AppConfig, store: Store) -> None:
    """负载感知的延迟图片处理：高 CPU（如打游戏）时排队，空闲后逐张处理。"""
    from .collection import (
        deferred_image_count,
        pop_deferred_image,
        process_event_image,
        requeue_deferred_image,
    )
    while True:
        item = pop_deferred_image()
        if item is None:
            await asyncio.sleep(2)
            continue
        if not load_aware_ok(config):
            requeue_deferred_image(item)
            print(f'load_aware: CPU busy，推迟图片处理（排队 {deferred_image_count()} 张）')
            await asyncio.sleep(load_aware_defer_seconds(config))
            continue
        scope, user_id, image, nearby_text, message_db_id, message_id = item
        event = {'message_id': message_id} if message_id is not None else None
        await asyncio.to_thread(
            process_event_image,
            store,
            scope=scope,
            user_id=user_id,
            image=image,
            nearby_text=nearby_text,
            message_db_id=message_db_id,
            config=config,
            event=event,
        )


async def background_sync_loop(config: AppConfig) -> None:
    """负载感知的后台图片同步：CPU 忙时推迟，空闲后执行重分类+还原+重建视图。"""
    last_sync = 0.0
    while True:
        if not load_aware_ok(config):
            print('load_aware: CPU busy，推迟图片同步')
            await asyncio.sleep(load_aware_defer_seconds(config))
            continue
        if _sync_requested.is_set() or (time.monotonic() - last_sync) >= 3600:
            try:
                counts = await asyncio.to_thread(
                    sync_image_files, _REPO_ROOT, ttl_hours=config.candidate_ttl_hours
                )
                print('image view synced: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
            except Exception as exc:
                print(f'image view sync failed: {type(exc).__name__}: {exc}')
            last_sync = time.monotonic()
            _sync_requested.clear()
            await asyncio.sleep(30)
        else:
            await asyncio.sleep(10)


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
    if _is_self_message(event):
        return False
    if event.get('post_type') != 'message':
        return False
    if event.get('message_type') == 'group':
        group_id = str(event.get('group_id') or '')
        _group_activity[group_id] = time.time()
        if (
            config.keepalive_enabled
            and config.keepalive_message.strip()
            and is_group_admin(event)
            and is_purge_announcement(event)
        ):
            # 管理员 @全体成员 宣布清理不活跃成员 → 冷却后立即发保活消息。
            now = time.monotonic()
            last_purge = _purge_keepalive_last.get(group_id)
            if last_purge is None or now - last_purge >= PURGE_KEEPALIVE_COOLDOWN_SECONDS:
                await _send_group_message(ws, group_id, config.keepalive_message)
                _purge_keepalive_last[group_id] = now
                _group_activity[group_id] = time.time()
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
    if config.relay_enabled:
        from .relay import relay_event
        asyncio.create_task(relay_event(ws, store, event, config))
    if not should_reply(event, config.bot):
        return False
    from .favorites import format_save_images_result, parse_save_images_command, save_replied_forward_images
    command_text = extract_text(event)
    save_category = parse_save_images_command(command_text)
    if save_category is not None:
        result = await save_replied_forward_images(store, event, config)
        await send_reply(ws, event, format_save_images_result(result, config.language))
        if result.get('saved', 0):
            request_image_sync()
        return True
    repair_command = parse_repair_images_command(command_text)
    if repair_command is not False:
        if event.get('message_type') != 'private':
            reply_text = (
                'The repair images command only works in private chat.'
                if config.language == 'en-US'
                else '“修复图片”只能在私聊中使用。'
            )
            await send_reply(ws, event, reply_text)
            return True
        from .image_repair import repair_damaged_images, repair_image
        tmp_dir = Path(config.data_dir) / 'tmp'
        archive_root = Path(config.data_dir) / 'images' / 'ai'
        if repair_command is None:
            result = await asyncio.to_thread(
                repair_damaged_images,
                store,
                tmp_dir=tmp_dir,
                archive_root=archive_root,
            )
            reply_text = (
                f"损坏图片扫描完成：扫描 {result['scanned']} 张，发现损坏 {result['damaged']} 张，"
                f"修复 {result['repaired']} 张，失败 {result['failed']} 张。"
            )
            if result['repaired']:
                request_image_sync()
        else:
            result = await asyncio.to_thread(
                repair_image,
                store,
                repair_command,
                tmp_dir=tmp_dir,
                archive_root=archive_root,
            )
            if result.get('status') == 'repaired':
                reply_text = f"图片 #{repair_command} 已重新下载并校验完成。"
                request_image_sync()
            else:
                reply_text = f"图片 #{repair_command} 修复失败：{result.get('reason', '未知错误')}"
        await send_reply(ws, event, reply_text)
        return True
    def load_aware_view_builder():
        from .build_image_view import stale_view_counts
        if not load_aware_ok(config):
            request_image_sync()
            return stale_view_counts(_REPO_ROOT / 'data' / 'view')
        return sync_image_files(_REPO_ROOT, ttl_hours=config.candidate_ttl_hours)
    reply = build_reply(
        event,
        store,
        default_summary_limit=config.default_summary_limit,
        max_summary_limit=config.max_summary_limit,
        view_builder=load_aware_view_builder,
        config_path=config_path,
        language=config.language,
    )
    if reply:
        await send_reply(ws, event, reply)
        return True
    if config.chat_enabled:
        from .chat import maybe_chat_reply
        chat_reply = await asyncio.to_thread(maybe_chat_reply, store, event, config)
        if chat_reply:
            await send_reply(ws, event, chat_reply)
            return True
    from .i18n import text as tr
    await send_reply(ws, event, tr('ack', config.language))
    return True


async def startup_history_catchup_worker(config: AppConfig, store: Store) -> None:
    try:
        async with websockets.connect(config.onebot_ws_url) as action_ws:
            await startup_history_catchup(action_ws, config, store)
        request_image_sync()
        print('startup history catch-up done; image view sync scheduled (load-aware)')
    except Exception as exc:
        print(f'startup history catch-up failed: {type(exc).__name__}: {exc}')


async def run(config: AppConfig, config_path: str | Path = 'config.yaml') -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / 'bot.db')
    from . import control
    retry_delay = 5
    while True:
        # 启动不再阻塞在完整同步上：交给后台负载感知循环（CPU 忙时自动推迟）
        sync_task = asyncio.create_task(background_sync_loop(config))
        image_task = asyncio.create_task(image_worker_loop(config, store))
        try:
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
                ai_task = None
                if config.feature_ai_context:
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
                    for task in (startup_task, report_task, ai_task, keepalive_task, status_task):
                        if task is not None:
                            task.cancel()
                    await asyncio.gather(
                        *(t for t in (startup_task, report_task, ai_task, keepalive_task, status_task)
                          if t is not None and not t.done()),
                        return_exceptions=True,
                    )
        except Exception as exc:
            # NapCat 未登录/未就绪时连接会被拒，重试等待而不是直接退出
            print(f'OneBot connect failed: {type(exc).__name__}: {exc}')
        finally:
            for task in (sync_task, image_task):
                task.cancel()
            await asyncio.gather(
                *(t for t in (sync_task, image_task) if not t.done()),
                return_exceptions=True,
            )
            control.write_status(
                {"napcat": control.port_open(control.NAPCAT_PORT),
                 "onebot": False, "bot": False,
                 "qqLoggedIn": False, "qqNumber": "", "qqNickname": "",
                 "manualStop": control.manual_stop_requested()}
            )
        print(f'OneBot disconnected; reconnecting in {retry_delay}s')
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60)


def main() -> int:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # 控制台非 UTF-8 时也绝不因打印 emoji 崩溃
    parser = argparse.ArgumentParser(description='OneBot whitelist @ bot')
    parser.add_argument('--config', default='config.yaml')
    args = parser.parse_args()
    asyncio.run(run(load_config(args.config), args.config))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import websockets

from .archive_budget import enforce_archive_budget
from .commands import build_reply, scope_for_event
from .config import AppConfig, load_config
from .ai_relevance import is_positive_feedback_text
from .ai_context_analyze import analyze_configured, configured_scopes
from .daily_report import build_daily_resource_report, should_run_daily_report, split_message, today_key
from .image_lifecycle import CandidateImage, promote_candidate
from .maintenance import sync_image_files
from .images import extract_image_segments, is_probable_sticker_result, process_image_url
from .policy import extract_text, should_reply
from .resources import extract_file_segments, extract_resource_links
from .schedule import is_in_time_windows
from .store import Store


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
    if not config.startup_history_enabled:
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
            if not next_seq or next_seq == seq:
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


def should_run_ai_context(config_path: str | Path, store: Store, now: datetime) -> tuple[bool, int, AppConfig]:
    current = load_config(config_path)
    scopes = [scope for scope in configured_scopes(current, current.data_dir / 'bot.db') if scope]
    pending = sum(
        store.count_messages_after(str(scope), store.last_ai_context_end_message_id(str(scope)))
        for scope in scopes
    )
    allowed = is_in_time_windows(now, current.ai_context_allowed_windows)
    return pending >= current.ai_context_min_new_messages and allowed, pending, current


async def ai_context_loop(config_path: str | Path, store: Store) -> None:
    running = False
    current = load_config(config_path)
    while True:
        try:
            should_run, pending, current = should_run_ai_context(config_path, store, datetime.now())
            if should_run and not running:
                running = True
                try:
                    print(f'ai_context auto run starting, pending messages={pending}')
                    await asyncio.to_thread(analyze_configured, str(config_path))
                    print('ai_context auto run finished')
                finally:
                    running = False
            elif pending >= current.ai_context_min_new_messages:
                print(f'ai_context waiting for allowed window, pending messages={pending}, windows={current.ai_context_allowed_windows}')
        except Exception as exc:
            print(f'ai_context_loop failed: {type(exc).__name__}: {exc}')
        await asyncio.sleep(max(1, current.ai_context_auto_interval_minutes) * 60)


async def daily_report_loop(ws, config: AppConfig, store: Store) -> None:
    while True:
        now = datetime.now()
        key = today_key(now)
        try:
            if should_run_daily_report(hour=now.hour, already_sent=store.has_daily_report(key)):
                since = store.last_daily_report_sent_at()
                content = build_daily_resource_report(store, since=since)
                if content:
                    chunks = split_message(content, max_chars=1800)
                    for user_id in sorted(config.bot.whitelist_users):
                        for idx, chunk in enumerate(chunks, 1):
                            prefix = f'资源日报 {idx}/{len(chunks)}\n' if len(chunks) > 1 else ''
                            await send_private(ws, user_id, prefix + chunk)
                    print(f'daily_report sent to {sorted(config.bot.whitelist_users)} chunks={len(chunks)} chars={len(content)}')
                    store.mark_daily_report_sent(key, content)
        except Exception as exc:
            print(f'daily_report_loop failed: {type(exc).__name__}: {exc}')
        await asyncio.sleep(300)


def promote_recent_candidate_if_needed(store: Store, scope: str, text: str, config: AppConfig) -> None:
    if not is_positive_feedback_text(text):
        return
    candidate = store.latest_candidate_image(scope)
    if not candidate:
        return
    path = candidate.get('kept_path')
    if not path:
        return
    if is_probable_sticker_result(candidate):
        return
    source = CandidateImage(scope=scope, sha256=str(candidate.get('sha256') or ''), path=Path(path), created_at=0, score=2)
    dest = promote_candidate(source, config.data_dir / 'images' / 'ai')
    store.update_image_retention(int(candidate['id']), kept_path=str(dest), retention_reason='positive_feedback')


def record_event(store: Store, event: dict[str, Any], config: AppConfig) -> None:
    if event.get('post_type') != 'message':
        return
    scope = scope_for_event(event)
    user_id = str(event.get('user_id') or '')
    text = extract_text(event)
    links = store.record_message(
        scope=scope,
        user_id=user_id,
        text=text,
        raw=event,
    )
    message_db_id = store.message_row_id(scope, event)
    for file_item in extract_file_segments(event):
        if file_item.get('kind') in {'model', 'archive', 'workflow'}:
            store.record_file(
                scope=scope,
                user_id=user_id,
                file_name=file_item['file_name'],
                file_size=file_item.get('file_size'),
                url=file_item.get('url'),
                kind=file_item.get('kind') or 'other',
                raw={'file': file_item, 'message_text': text},
            )
    nearby_text = '\n'.join(x for x in [store.recent_text_context(scope, limit=8), text] if x)
    promote_recent_candidate_if_needed(store, scope, text, config)
    for image in extract_image_segments(event):
        try:
            result = process_image_url(
                image['url'],
                tmp_dir=config.data_dir / 'tmp',
                archive_root=config.data_dir / 'images' / 'ai',
                candidate_root=config.data_dir / 'images' / 'candidates',
                filename_hint=image.get('file'),
                nearby_text=nearby_text,
            )
            if is_probable_sticker_result(result) and result.get('retention_reason') in {'positive_feedback', 'nearby_ai_context', 'candidate'}:
                kept = result.get('kept_path')
                if kept:
                    Path(kept).unlink(missing_ok=True)
                result['kept_path'] = None
                result['retention_reason'] = 'sticker_filtered'
            store.record_image(
                scope=scope,
                user_id=user_id,
                result=result,
                raw={'image': image, 'message_db_id': message_db_id, 'message_id': event.get('message_id')},
            )
            # Saved images under data/images/ai are archive, not cache.
            # Do not enforce a size budget here; only candidates are temporary.
        except Exception as exc:
            print(f'image processing failed: {type(exc).__name__}: {exc}')


def is_blocked_event(event: dict[str, Any], config: AppConfig) -> bool:
    return event.get('message_type') == 'group' and str(event.get('group_id') or '') in config.blocked_groups


async def handle_event(ws, event: dict[str, Any], config: AppConfig, store: Store, config_path: str | Path = 'config.yaml') -> bool:
    if event.get('post_type') != 'message':
        return False
    if is_blocked_event(event, config):
        return False
    record_event(store, event, config)
    if not should_reply(event, config.bot):
        return False
    reply = build_reply(
        event,
        store,
        default_summary_limit=config.default_summary_limit,
        max_summary_limit=config.max_summary_limit,
        view_builder=lambda: sync_image_files(Path.cwd()),
        config_path=config_path,
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
        startup_task = asyncio.create_task(startup_history_catchup_worker(config, store))
        report_task = asyncio.create_task(daily_report_loop(ws, config, store))
        ai_task = asyncio.create_task(ai_context_loop(config_path, store))
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


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='OneBot whitelist @ bot')
    parser.add_argument('--config', default='config.yaml')
    args = parser.parse_args()
    asyncio.run(run(load_config(args.config), args.config))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

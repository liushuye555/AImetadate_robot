from __future__ import annotations

import asyncio
import argparse
import json
from typing import Any

import websockets

from .config import AppConfig, load_config
from .onebot import handle_event
from .store import Store


def message_key(event: dict[str, Any]) -> int | str | None:
    return event.get('message_seq') or event.get('message_id') or event.get('real_id')


async def onebot_call(ws, action: str, params: dict[str, Any] | None = None, *, echo: str = 'call') -> dict[str, Any]:
    await ws.send(json.dumps({'action': action, 'params': params or {}, 'echo': echo}, ensure_ascii=False))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get('echo') == echo:
            return data


async def list_groups(config: AppConfig, *, mode: str | None = None) -> list[int]:
    selected_mode = (mode or config.startup_history_mode or 'whitelist').lower()
    if selected_mode == 'whitelist':
        return [int(x) for x in sorted(config.startup_history_groups)]
    async with websockets.connect(config.onebot_ws_url) as ws:
        resp = await onebot_call(ws, 'get_group_list', echo='group-list')
    groups = []
    for item in (resp.get('data') or []):
        gid = str(item.get('group_id') or '')
        if not gid:
            continue
        if gid in config.blocked_groups:
            continue
        groups.append(int(gid))
    return groups


async def import_group_history_once(
    ws,
    config: AppConfig,
    store: Store,
    *,
    group_id: int,
    count: int = 20,
    message_seq: int | str = 0,
    reverse_order: bool = False,
    seen: set[int | str] | None = None,
    stop_at_key: int | str | None = None,
) -> tuple[int, int | str | None]:
    echo = 'history'
    resp = await onebot_call(
        ws,
        'get_group_msg_history',
        {
            'group_id': int(group_id),
            'count': int(count),
            'message_seq': str(message_seq or 0),
            'reverse_order': bool(reverse_order),
        },
        echo=echo,
    )
    seen = seen if seen is not None else set()
    messages = ((resp.get('data') or {}).get('messages') or []) if resp.get('status') == 'ok' else []
    imported = 0
    batch_keys = []
    for event in messages:
        key = message_key(event)
        if key is not None:
            batch_keys.append(key)
        if stop_at_key is not None and key is not None and str(key) == str(stop_at_key):
            break
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        if event.get('post_type') != 'message':
            event['post_type'] = 'message'
        await handle_event(ws, event, config, store)
        imported += 1
    next_seq = batch_keys[0] if batch_keys else None
    return imported, next_seq


async def import_group_history(config: AppConfig, *, group_id: int, pages: int = 1, count: int = 20, stop_at_known_newest: bool = True) -> int:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / 'bot.db')
    cursor = store.get_history_cursor(group_id)
    known_newest = str(cursor.get('newest_seq')) if cursor and cursor.get('newest_seq') else None
    total = 0
    seen: set[int | str] = set()
    message_seq: int | str = 0
    newest_seen: str | None = None
    oldest_seen: str | None = None
    async with websockets.connect(config.onebot_ws_url) as ws:
        for page in range(max(1, int(pages))):
            imported, next_seq = await import_group_history_once(
                ws,
                config,
                store,
                group_id=group_id,
                count=count,
                message_seq=message_seq,
                reverse_order=page > 0,
                seen=seen,
                stop_at_key=known_newest if stop_at_known_newest else None,
            )
            if seen and newest_seen is None:
                newest_seen = str(next(iter(seen)))
            if next_seq:
                oldest_seen = str(next_seq)
            total += imported
            if not next_seq or imported == 0:
                break
            message_seq = next_seq
            await asyncio.sleep(0.3)
    if newest_seen or oldest_seen:
        store.update_history_cursor(group_id, newest_seq=newest_seen, oldest_seq=oldest_seen)
    return total


async def import_history(config: AppConfig, *, group: int | None, mode: str | None, all_history: bool, pages: int | None, max_pages: int | None, count: int | None) -> int:
    if group is not None:
        groups = [int(group)]
    else:
        groups = await list_groups(config, mode=mode)
    page_limit = int(max_pages or config.startup_history_max_pages) if all_history else int(pages or config.startup_history_pages)
    item_count = int(count or config.startup_history_count)
    grand_total = 0
    print(f'history import groups={groups} pages={page_limit} count={item_count}')
    for gid in groups:
        total = await import_group_history(config, group_id=gid, pages=page_limit, count=item_count, stop_at_known_newest=not all_history)
        print(f'group {gid}: imported {total} messages')
        grand_total += total
    return grand_total


def main() -> int:
    parser = argparse.ArgumentParser(description='Import group message history via OneBot get_group_msg_history')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--group', type=int, required=False, help='Specific group id. Omit to use startup_history mode/groups.')
    parser.add_argument('--mode', choices=['whitelist', 'blacklist'], default=None, help='Group selection mode when --group is omitted.')
    parser.add_argument('--all', action='store_true', help='Keep paging until empty/no progress or --max-pages.')
    parser.add_argument('--pages', type=int, default=None, help='Pages per group when --all is not set.')
    parser.add_argument('--max-pages', type=int, default=None, help='Safety page cap when --all is set.')
    parser.add_argument('--count', type=int, default=None, help='Messages per page')
    args = parser.parse_args()
    total = asyncio.run(import_history(
        load_config(args.config),
        group=args.group,
        mode=args.mode,
        all_history=bool(args.all),
        pages=args.pages,
        max_pages=args.max_pages,
        count=args.count,
    ))
    print(f'imported {total} messages')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

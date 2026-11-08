"""Resumable, read-only group history archive, separate from live message handlers.

Stores original events and text/link records in bot.db. Media references are kept
in raw_json; fetching every attachment is a separate operation.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from . import gateway
from .config import load_config
from .store import Store


# User policy: keep collected data and stop at an unavailable history boundary.
# Resuming this checkpoint must not keep probing these same boundaries.
BOUNDARY_STATUSES = frozenset({'available_end', 'no_progress', 'empty_unverified'})


def now():
    return datetime.now(timezone.utc).isoformat()


def write_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f'.tmp-{os.getpid()}')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


@contextmanager
def task_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


async def backfill_group(config, store, ws, group_id, state, save, *, count=100, delay=0.3):
    """Continue through existing rows; stop only at an API boundary or failure."""
    anchor = state.get('anchor', 0)
    state.update(status='running', error='')
    visited = {str(anchor)} if anchor else set()
    while True:
        response = await gateway.call(ws, 'get_group_msg_history',
                                      gateway.history_params(config, group_id, anchor, count, True), timeout=45)
        messages = (response.get('data') or {}).get('messages') or []
        if not messages:
            # An unseeded SnowLuma session can return [] without asking QQ for
            # anything. No rows on the very first page is not proof of coverage.
            status = 'available_end' if state.get('pages', 0) else 'empty_unverified'
            state.update(status=status, updated_at=now())
            save()
            return state
        if any(not isinstance(m, dict) or str(m.get('group_id')) != str(group_id) for m in messages):
            raise ValueError('History response contains an unexpected group')
        messages = sorted(messages, key=lambda m: (int(m.get('time') or 0), int(m.get('message_seq') or 0)))
        next_anchor = gateway.history_anchor(config, messages)
        # Archival path deliberately avoids commands, replies, relays and AI calls.
        events = [gateway.normalize_event({**message, 'post_type': 'message', 'message_type': 'group'}) for message in messages]
        for attempt in range(6):
            try:
                inserted = await asyncio.to_thread(store.record_history_page, scope=f'group:{group_id}', events=events)
                break
            except sqlite3.OperationalError as exc:
                if not any(word in str(exc).lower() for word in ('locked', 'busy')) or attempt == 5:
                    raise
                state.update(status='retrying', error='database_busy')
                save()
                await asyncio.sleep(min(2 ** attempt, 8))
        state.update(status='running', error='')
        state['imported'] = state.get('imported', 0) + inserted
        for event in events:
            timestamp = int(event.get('time') or 0)
            if timestamp:
                state['oldest_time'] = min(state.get('oldest_time') or timestamp, timestamp)
                state['newest_time'] = max(state.get('newest_time') or timestamp, timestamp)
        state['pages'] = state.get('pages', 0) + 1
        state['updated_at'] = now()
        if next_anchor is None or str(next_anchor) in visited:
            state['status'] = 'no_progress'
            save()
            return state
        anchor = next_anchor
        visited.add(str(anchor))
        state['anchor'] = anchor
        save()
        if state['pages'] % 25 == 0:
            print(f'group={group_id} pages={state["pages"]} new={state.get("imported", 0)} oldest={state.get("oldest_time")}', flush=True)
        await asyncio.sleep(delay)


async def run(config, path, *, count=200, delay=0.3, concurrency=2):
    if config.onebot_provider == 'qqofficial':
        raise ValueError('QQ official API does not provide group history')
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'groups': {}, 'started_at': now()}
    async with gateway.connect(config) as ws:
        login = (await gateway.call(ws, 'get_login_info')).get('data') or {}
        identity = {'provider': config.onebot_provider, 'account': str(login.get('user_id') or '')}
        if not identity['account']:
            raise ValueError('QQ account is not logged in')
        if state.get('identity') and state['identity'] != identity:
            raise ValueError('Checkpoint belongs to another framework/account; use another state file')
        state.update(identity=identity, status='running', pid=os.getpid(), updated_at=now())
        groups = (await gateway.call(ws, 'get_group_list')).get('data') or []
    state['excluded_groups'] = sorted(config.blocked_groups)
    selected = [g for g in groups if str(g['group_id']) not in config.blocked_groups]
    state['selected_groups'] = [str(g['group_id']) for g in selected]
    def save():
        state['updated_at'] = now()
        write_state(path, state)
    save()
    store = Store(config.data_dir / 'bot.db')
    semaphore = asyncio.Semaphore(concurrency)

    async def archive(group):
        gid = str(group['group_id'])
        progress = state['groups'].setdefault(gid, {})
        progress['name'] = group.get('group_name', '')
        if progress.get('status') in BOUNDARY_STATUSES:
            return
        # Retain the boundary reason without treating inaccessible records as restored.
        try:
            for attempt in range(3):
                try:
                    async with gateway.connect(config) as ws:
                        await backfill_group(config, store, ws, int(gid), progress, save, count=count, delay=delay)
                    break
                except (TimeoutError, OSError, gateway.ActionError) as exc:
                    progress.update(status='retrying', error=type(exc).__name__)
                    save()
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 * (attempt + 1))
        except Exception as exc:
            progress.update(status='failed', error=type(exc).__name__, updated_at=now())
            save()
        print(f'group={gid} status={progress.get("status")} new={progress.get("imported", 0)} pages={progress.get("pages", 0)}', flush=True)
    async def limited_archive(group):
        async with semaphore:
            await archive(group)

    await asyncio.gather(*(limited_archive(group) for group in selected))
    statuses = {state['groups'][gid].get('status') for gid in state['selected_groups']}
    if statuses <= {'available_end'}:
        status = 'finished'
    elif statuses <= BOUNDARY_STATUSES:
        status = 'finished_with_limits'
    else:
        status = 'needs_attention'
    state.update(status=status, updated_at=now())
    save()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--state', default='run/full-history.json')
    parser.add_argument('--count', type=int, default=200)
    parser.add_argument('--delay', type=float, default=0.3)
    parser.add_argument('--concurrency', type=int, default=2)
    args = parser.parse_args()
    if args.count < 2 or args.delay < 0 or not 1 <= args.concurrency <= 4:
        parser.error('count must be >= 2, delay >= 0, and concurrency between 1 and 4')
    path = Path(args.state)
    with task_lock(path.with_suffix('.lock')):
        state = asyncio.run(run(load_config(args.config), path, count=args.count, delay=args.delay, concurrency=args.concurrency))
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return 0 if state['status'] in ('finished', 'finished_with_limits') else 2


if __name__ == '__main__':
    raise SystemExit(main())

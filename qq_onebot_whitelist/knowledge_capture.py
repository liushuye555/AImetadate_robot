"""Durable local attachment capture, independent of AI analysis and its schedule."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading

from .config import load_config
from .knowledge_config import enabled_profiles, profile_for
from .knowledge_store import KnowledgeDB, LOCAL_TZ
from .resources import extract_file_segments


_WORKER_LOCK = threading.Lock()


def enqueue_event_files(config, scope: str, event: dict, message_id: int) -> int:
    if not scope.startswith('group:'):
        return 0
    profile = profile_for(config, scope)
    if not profile.allows('files') or (profile.settings.get('files') or {}).get('mode') != 'save_all':
        return 0
    if not config.collection_groups.get(scope, {}).get('files', True):
        return 0
    files = extract_file_segments(event)
    if not files:
        return 0
    db = KnowledgeDB(config.data_dir / 'knowledge.db')
    return sum(db.queue_asset({**source, 'scope': scope, 'message_id': message_id})
               for source in files if source.get('file_id'))


def capture_tick(config_path: Path | str) -> dict:
    """Save fresh arrivals first; failed downloads retry after a ten-minute cooldown."""
    if not _WORKER_LOCK.acquire(blocking=False):
        return {'attempted': 0}
    try:
        from .collection import is_collection_paused
        if is_collection_paused():
            return {'attempted': 0}
        config = load_config(config_path)
        profiles = [p for p in enabled_profiles(config) if p.allows('files')
                    and (p.settings.get('files') or {}).get('mode') == 'save_all']
        if not profiles:
            return {'attempted': 0}
        from .knowledge import retain_selected_files
        db = KnowledgeDB(config.data_dir / 'knowledge.db')
        cutoff = (datetime.now(LOCAL_TZ) - timedelta(minutes=10)).isoformat()
        attempted = 0
        for profile in profiles:
            if not config.collection_groups.get(profile.scope, {}).get('files', True):
                continue
            with db.conn() as conn:
                rows = conn.execute(
                    "SELECT source_json FROM assets WHERE scope=? AND "
                    "(status='pending' OR (status='failed' AND last_attempt_at<=?)) "
                    "ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END,last_attempt_at,file_id LIMIT 2",
                    (profile.scope, cutoff)).fetchall()
            sources = [json.loads(row['source_json']) for row in rows]
            if sources:
                retain_selected_files(Path(config_path), db, [{'scope': profile.scope, 'files': sources}],
                                      {'items': [{'file_ids': [f['file_id'] for f in sources]}]},
                                      capture=True)
                attempted += len(sources)
        return {'attempted': attempted}
    finally:
        _WORKER_LOCK.release()


async def capture_loop(config_path: Path | str):
    async def refresh_view():
        try:
            from .knowledge import write_view
            config = load_config(config_path)
            await asyncio.to_thread(write_view, config.data_dir, config)
        except Exception as exc:
            print(f'file capture report: {type(exc).__name__}')

    refresh = None
    dirty = False
    try:
        while True:
            try:
                result = await asyncio.to_thread(capture_tick, config_path)
                dirty = dirty or bool(result['attempted'])
                # Rendering knowledge pages can take much longer than saving a
                # small attachment. Never make the download queue wait for it.
                if dirty and (refresh is None or refresh.done()):
                    refresh = asyncio.create_task(refresh_view())
                    dirty = False
            except Exception as exc:
                print(f'local file capture: {type(exc).__name__}')
            await asyncio.sleep(1)
    finally:
        if refresh is not None:
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)

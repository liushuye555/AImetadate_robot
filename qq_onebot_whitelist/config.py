from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
import os
import yaml

from .policy import BotConfig
from .schedule import normalize_time_windows


@dataclass(slots=True)
class AppConfig:
    onebot_ws_url: str = 'ws://127.0.0.1:3001'
    data_dir: Path = Path('data')
    bot: BotConfig = field(default_factory=BotConfig)
    default_summary_limit: int = 100
    max_summary_limit: int = 500
    blocked_groups: set[str] = field(default_factory=set)
    max_archive_mb: int = 500
    candidate_ttl_hours: int = 24
    startup_history_enabled: bool = True
    startup_history_mode: str = 'whitelist'
    startup_history_groups: set[str] = field(default_factory=set)
    startup_history_pages: int = 3
    startup_history_count: int = 20
    startup_history_all: bool = False
    startup_history_max_pages: int = 200
    ai_context_enabled: bool = True
    ai_context_provider: str = 'ds_v4_flash'
    ai_context_scopes: str | list[str] = 'all_groups'
    ai_context_chunk_size: int = 200
    ai_context_max_chunks: int | None = None
    ai_context_auto_interval_minutes: int = 15
    ai_context_min_new_messages: int = 300
    ai_context_allowed_windows: list[str] = field(default_factory=list)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
    raw = raw or {}
    onebot = raw.get('onebot') or {}
    reply = raw.get('reply') or {}
    storage = raw.get('storage') or {}
    summary = raw.get('summary') or {}
    listen = raw.get('listen') or {}
    images = raw.get('images') or {}
    startup_history = raw.get('startup_history') or {}
    ai_context = raw.get('ai_context') or {}
    return AppConfig(
        onebot_ws_url=str(onebot.get('ws_url') or 'ws://127.0.0.1:3001'),
        data_dir=Path(storage.get('data_dir') or 'data'),
        bot=BotConfig(
            whitelist_users={str(x) for x in (reply.get('whitelist_users') or [])},
            whitelist_groups={str(x) for x in (reply.get('whitelist_groups') or [])},
            require_at_in_group=bool(reply.get('require_at_in_group', True)),
            allow_group_admins=bool(reply.get('allow_group_admins', True)),
        ),
        default_summary_limit=int(summary.get('default_limit') or 100),
        max_summary_limit=int(summary.get('max_limit') or 500),
        blocked_groups={str(x) for x in (listen.get('blocked_groups') or [])},
        max_archive_mb=int(images.get('max_archive_mb') or 500),
        candidate_ttl_hours=int(images.get('candidate_ttl_hours') or 24),
        startup_history_enabled=bool(startup_history.get('enabled', True)),
        startup_history_mode=str(startup_history.get('mode') or 'whitelist').lower(),
        startup_history_groups={str(x) for x in (startup_history.get('groups') or [])},
        startup_history_pages=int(startup_history.get('pages') or 3),
        startup_history_count=int(startup_history.get('count') or 20),
        startup_history_all=bool(startup_history.get('all', False)),
        startup_history_max_pages=int(startup_history.get('max_pages') or 200),
        ai_context_enabled=bool(ai_context.get('enabled', True)),
        ai_context_provider=str(ai_context.get('provider') or 'ds_v4_flash').lower(),
        ai_context_scopes=ai_context.get('scopes') or 'all_groups',
        ai_context_chunk_size=int(ai_context.get('chunk_size') or 200),
        ai_context_max_chunks=(int(ai_context['max_chunks']) if ai_context.get('max_chunks') is not None else None),
        ai_context_auto_interval_minutes=int(ai_context.get('auto_interval_minutes') or 15),
        ai_context_min_new_messages=int(ai_context.get('min_new_messages') or 300),
        ai_context_allowed_windows=normalize_time_windows([str(x) for x in (ai_context.get('allowed_windows') or [])]),
    )

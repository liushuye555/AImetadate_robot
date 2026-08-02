from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
import os
import yaml

from .policy import BotConfig
from .schedule import normalize_time_windows
from .i18n import effective_language, normalize_language


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
    sticker_repeat_threshold: int = 3
    startup_history_enabled: bool = True
    startup_history_mode: str = 'whitelist'
    startup_history_groups: set[str] = field(default_factory=set)
    startup_history_pages: int = 3
    startup_history_count: int = 20
    startup_history_all: bool = False
    startup_history_max_pages: int = 200
    ai_context_enabled: bool = True
    ai_context_provider: str = 'ds_v4_flash'
    ai_context_providers: dict[str, dict[str, str]] = field(default_factory=dict)
    ai_context_scopes: str | list[str] = 'all_groups'
    ai_context_chunk_size: int = 200
    ai_context_max_chunks: int | None = None
    ai_context_auto_interval_minutes: int = 15
    ai_context_min_new_messages: int = 300
    ai_context_allowed_windows: list[str] = field(default_factory=list)
    language: str = 'en-US'
    daily_report_enabled: bool = True
    daily_report_hour: int = 20
    daily_report_max_links: int = 20
    daily_report_enrich_links: bool = True
    daily_report_max_enriched_links: int = 8
    daily_report_include_links: bool = True
    daily_report_include_files: bool = True
    echo_enabled: bool = False
    echo_min_repeat: int = 3
    echo_window_seconds: int = 60
    echo_groups: set[str] = field(default_factory=set)
    collection_groups: dict[str, dict[str, bool]] = field(default_factory=dict)
    collection_rules: list[dict] = field(default_factory=list)
    collection_expand_forwards: bool = False
    load_aware_enabled: bool = True
    load_aware_cpu_threshold: int = 80
    load_aware_check_seconds: int = 60
    feature_link_analysis: bool = True
    feature_link_metadata: bool = True
    feature_image_processing: bool = True
    feature_ai_context: bool = True
    feature_daily_report: bool = True
    feature_startup_history: bool = True
    feature_auto_restart: bool = True
    keepalive_enabled: bool = False
    keepalive_interval_minutes: int = 0
    keepalive_groups: set[str] = field(default_factory=set)
    keepalive_message: str = ''
    keepalive_mode: str = 'all'
    keepalive_trigger_enabled: bool = False
    keepalive_idle_minutes: int = 60


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
    ui = raw.get('ui') or {}
    daily_report = raw.get('daily_report') or {}
    features = raw.get('features') or {}
    keepalive = raw.get('keepalive') or {}
    echo = raw.get('echo') or {}
    collection = raw.get('collection') or {}
    load_aware = raw.get('load_aware') or {}
    configured_language = normalize_language(ui.get('language'))
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
        sticker_repeat_threshold=int(images.get('sticker_repeat_threshold') or 3),
        startup_history_enabled=bool(startup_history.get('enabled', True)),
        startup_history_mode=str(startup_history.get('mode') or 'whitelist').lower(),
        startup_history_groups={str(x) for x in (startup_history.get('groups') or [])},
        startup_history_pages=int(startup_history.get('pages') or 3),
        startup_history_count=int(startup_history.get('count') or 20),
        startup_history_all=bool(startup_history.get('all', False)),
        startup_history_max_pages=int(startup_history.get('max_pages') or 200),
        ai_context_enabled=bool(ai_context.get('enabled', True)),
        ai_context_provider=str(ai_context.get('provider') or 'ds_v4_flash').lower(),
        ai_context_providers={str(key): {str(k): str(v) for k, v in (value or {}).items()} for key, value in (ai_context.get('providers') or {}).items() if isinstance(value, dict)},
        ai_context_scopes=ai_context.get('scopes') or 'all_groups',
        ai_context_chunk_size=int(ai_context.get('chunk_size') or 200),
        ai_context_max_chunks=(int(ai_context['max_chunks']) if str(ai_context.get('max_chunks') or '').strip() else None),
        ai_context_auto_interval_minutes=int(ai_context.get('auto_interval_minutes') or 15),
        ai_context_min_new_messages=int(ai_context.get('min_new_messages') or 300),
        ai_context_allowed_windows=normalize_time_windows([str(x) for x in (ai_context.get('allowed_windows') or [])]),
        language=effective_language(configured_language),
        daily_report_enabled=bool(daily_report.get('enabled', True)),
        daily_report_hour=int(daily_report.get('hour') or 20),
        daily_report_max_links=int(daily_report.get('max_links') or 20),
        daily_report_enrich_links=bool(daily_report.get('enrich_links', True)),
        daily_report_max_enriched_links=int(daily_report.get('max_enriched_links') or 8),
        daily_report_include_links=bool(daily_report.get('include_links', True)),
        daily_report_include_files=bool(daily_report.get('include_files', True)),
        echo_enabled=bool(echo.get('enabled', False)),
        echo_min_repeat=int(echo.get('min_repeat') or 3),
        echo_window_seconds=int(echo.get('window_seconds') or 60),
        echo_groups={str(x) for x in (echo.get('groups') or [])},
        collection_groups={
            str(key): {str(k2): bool(v2) for k2, v2 in (value or {}).items()}
            for key, value in (collection.get('groups') or {}).items()
            if isinstance(value, dict)
        },
        collection_rules=[dict(rule) for rule in (collection.get('rules') or []) if isinstance(rule, dict)],
        collection_expand_forwards=bool(collection.get('expand_forwards', False)),
        load_aware_enabled=bool(load_aware.get('enabled', True)),
        load_aware_cpu_threshold=int(load_aware.get('cpu_threshold') or 80),
        load_aware_check_seconds=int(load_aware.get('check_seconds') or 60),
        feature_link_analysis=bool(features.get('link_analysis', True)),
        feature_link_metadata=bool(features.get('link_metadata', daily_report.get('enrich_links', True))),
        feature_image_processing=bool(features.get('image_processing', True)),
        feature_ai_context=bool(features.get('ai_context', ai_context.get('enabled', True))),
        feature_daily_report=bool(features.get('daily_report', daily_report.get('enabled', True))),
        feature_startup_history=bool(features.get('startup_history', startup_history.get('enabled', True))),
        feature_auto_restart=bool(features.get('auto_restart', True)),
        keepalive_enabled=bool(keepalive.get('enabled', False)),
        keepalive_interval_minutes=int(keepalive.get('interval_minutes') or 0),
        keepalive_groups={str(x) for x in (keepalive.get('groups') or [])},
        keepalive_message=str(keepalive.get('message') or ''),
        keepalive_mode=str(keepalive.get('mode') or 'all').lower(),
        keepalive_trigger_enabled=bool(keepalive.get('trigger_enabled', False)),
        keepalive_idle_minutes=int(keepalive.get('idle_minutes') or 60),
    )

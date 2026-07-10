from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .config import AppConfig, load_config
from .context_quality import parse_context_quality
from .llm_summary import LLMConfig, summarize_records_with_fallback
from .store import Store, raw_message_ids, reply_to_message_id


def fetch_records(db_path: Path, *, scope: str | None, after_id: int = 0, limit: int = 500) -> list[dict]:
    sql = 'SELECT id, seen_at, scope, user_id, text, links_json, raw_json FROM messages WHERE id > ?'
    args: list = [after_id]
    if scope:
        sql += ' AND scope = ?'
        args.append(scope)
    sql += ' ORDER BY id ASC LIMIT ?'
    args.append(limit)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    parsed_rows = []
    for r in rows:
        try:
            links = json.loads(r['links_json'] or '[]')
        except Exception:
            links = []
        try:
            raw = json.loads(r['raw_json'] or '{}')
        except Exception:
            raw = {}
        sender = raw.get('sender') or {}
        parsed_rows.append((r, raw, sender, links))
    quoted_by_id: dict[str, str] = {}
    for r, raw, _sender, _links in parsed_rows:
        for message_id in raw_message_ids(raw):
            quoted_by_id[message_id] = str(r['text'] or '')
    missing_reply_ids = {
        reply_id
        for _r, raw, _sender, _links in parsed_rows
        if (reply_id := reply_to_message_id(raw)) and reply_id not in quoted_by_id
    }
    if missing_reply_ids:
        placeholders = ','.join('?' for _ in missing_reply_ids)
        conn = sqlite3.connect(db_path)
        older_rows = conn.execute(
            f'SELECT text, raw_json FROM messages WHERE scope = ? AND message_key IN ({placeholders})',
            [scope, *missing_reply_ids],
        ).fetchall()
        conn.close()
        for text, raw_json in older_rows:
            try:
                older_raw = json.loads(raw_json or '{}')
            except Exception:
                older_raw = {}
            for message_id in raw_message_ids(older_raw):
                quoted_by_id[message_id] = str(text or '')
    records = []
    for r, raw, sender, links in parsed_rows:
        reply_id = reply_to_message_id(raw)
        records.append({
            'id': r['id'], 'seen_at': r['seen_at'], 'scope': r['scope'], 'user_id': r['user_id'],
            'nickname': sender.get('nickname') or '', 'card': sender.get('card') or '',
            'text': r['text'], 'links': links, 'quoted_text': quoted_by_id.get(reply_id or ''),
        })
    return records


def configured_scopes(config: AppConfig, db_path: Path) -> list[str | None]:
    scopes = config.ai_context_scopes
    if scopes in (None, 'all', 'all_messages'):
        return [None]
    if scopes == 'all_groups':
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT DISTINCT scope FROM messages WHERE scope LIKE 'group:%' ORDER BY scope").fetchall()
        conn.close()
        result = []
        for (scope,) in rows:
            group_id = str(scope).split(':', 1)[1]
            if group_id in config.blocked_groups:
                continue
            result.append(str(scope))
        return result
    if isinstance(scopes, list):
        return [str(x) for x in scopes]
    return [str(scopes)]


def llm_configs_for_provider(provider: str) -> tuple[LLMConfig | None, LLMConfig | None]:
    provider = (provider or '').lower()
    if provider in {'ds', 'ds_v4_flash', 'deepseek', 'deepseek_v4_flash'}:
        return LLMConfig.ds_fallback_from_env_file(), None
    if provider in {'openrouter', 'free', 'openrouter_free'}:
        return LLMConfig.from_env(), LLMConfig.ds_fallback_from_env_file()
    if provider in {'auto', 'default'}:
        return LLMConfig.from_env(), LLMConfig.ds_fallback_from_env_file()
    raise SystemExit(f'Unknown ai_context.provider: {provider}')


def user_alias_map(records: list[dict]) -> dict[str, dict[str, str]]:
    users: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for record in records:
        user_id = str(record.get('user_id') or 'unknown')
        if user_id not in seen:
            seen.add(user_id)
            users[f'U{len(users) + 1}'] = {
                'user_id': user_id,
                'nickname': str(record.get('nickname') or ''),
                'card': str(record.get('card') or ''),
            }
    return users


def analyze_scope(
    config_path: str,
    *,
    scope: str | None,
    chunk_size: int | None = None,
    max_chunks: int | None = None,
    dry_run: bool = False,
    allow_ds_fallback: bool | None = None,
) -> int:
    config = load_config(config_path)
    if not config.ai_context_enabled:
        print('ai_context disabled in config')
        return 0
    store = Store(config.data_dir / 'bot.db')
    primary, fallback = llm_configs_for_provider(config.ai_context_provider)
    if allow_ds_fallback is False:
        fallback = None
    elif allow_ds_fallback is True and fallback is None:
        fallback = LLMConfig.ds_fallback_from_env_file()
    if not primary and not fallback:
        raise SystemExit('LLM config missing')
    size = int(chunk_size or config.ai_context_chunk_size)
    limit_chunks = max_chunks if max_chunks is not None else config.ai_context_max_chunks
    after_id = store.last_ai_context_end_message_id(scope) if scope else 0
    chunks = 0
    total = 0
    db_path = config.data_dir / 'bot.db'
    while True:
        if limit_chunks is not None and chunks >= limit_chunks:
            break
        records = fetch_records(db_path, scope=scope, after_id=after_id, limit=size)
        if not records:
            break
        after_id = records[-1]['id']
        chunks += 1
        total += len(records)
        batch_scope = scope or records[0]['scope']
        active_model = primary.model if primary else (fallback.model if fallback else 'unknown')
        print(f'chunk {chunks}: scope {batch_scope}, ids {records[0]["id"]}-{records[-1]["id"]}, messages {len(records)}, model {active_model}')
        if dry_run:
            continue
        summary = summarize_records_with_fallback(records, primary, fallback)
        quality = parse_context_quality(summary)
        store.record_ai_context_batch(
            scope=batch_scope,
            start_message_id=records[0]['id'],
            end_message_id=records[-1]['id'],
            model=active_model,
            summary=quality.display_summary,
            raw_json=json.dumps({
                'message_count': len(records),
                'provider': config.ai_context_provider,
                'users': user_alias_map(records),
                'quality': {
                    'ai_relevant': quality.ai_relevant,
                    'value_level': quality.value_level,
                    'reason': quality.reason,
                },
            }, ensure_ascii=False),
        )
        print(summary[:300].replace('\n', ' | '))
    print(f'analyzed {total} messages in {chunks} chunks for {scope or "all"}')
    return total


def analyze_configured(config_path: str, *, scope_override: str | None = None, chunk_size: int | None = None, max_chunks: int | None = None, dry_run: bool = False) -> int:
    config = load_config(config_path)
    db_path = config.data_dir / 'bot.db'
    scopes = [scope_override] if scope_override else configured_scopes(config, db_path)
    print('ai_context scopes:', ', '.join(str(s) for s in scopes))
    total = 0
    for scope in scopes:
        total += analyze_scope(config_path, scope=scope, chunk_size=chunk_size, max_chunks=max_chunks, dry_run=dry_run, allow_ds_fallback=None)
    print(f'ai_context total analyzed {total} messages across {len(scopes)} scope(s)')
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description='Batch LLM analysis for AI drawing group contexts')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--scope', default=None, help='Override configured scopes, e.g. group:100000002')
    parser.add_argument('--chunk-size', type=int, default=None, help='Override ai_context.chunk_size')
    parser.add_argument('--max-chunks', type=int, default=None, help='Override ai_context.max_chunks per scope')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    analyze_configured(args.config, scope_override=args.scope, chunk_size=args.chunk_size, max_chunks=args.max_chunks, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

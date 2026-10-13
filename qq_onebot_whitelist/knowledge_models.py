"""Opt-in knowledge model routing and persistent provider health.

Configuration resolution does not contact a model. Callers must check ``permit``
before reserving a request budget, and report only request/validation failures
that should count against provider health. Construct a breaker only when the
group's ``circuit_enabled`` setting is exactly True.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator
import uuid

from .llm_summary import LLMConfig, normalize_base_url


def _model_settings(settings: dict[str, Any]) -> dict[str, Any]:
    values = settings.get('models', settings)
    return values if isinstance(values, dict) else {}


def _provider(name: Any, env_path: Path | None) -> LLMConfig | None:
    if name == 'default':
        return LLMConfig.from_env() if env_path is None else LLMConfig.from_env_file(env_path)
    if name == 'ds_v4_flash':
        return LLMConfig.ds_fallback_from_env_file() if env_path is None else LLMConfig.ds_fallback_from_env_file(env_path)
    raise ValueError('supported model providers are default and ds_v4_flash')


def _identity(cfg: LLMConfig) -> str:
    # Length-delimited encoding avoids ambiguous concatenation; only the digest
    # is persisted. A credential change deliberately starts fresh health state.
    encoded = json.dumps(
        [normalize_base_url(cfg.base_url), cfg.model, cfg.api_key],
        ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _override_model(cfg: LLMConfig | None, model: Any) -> LLMConfig | None:
    if cfg is not None and isinstance(model, str) and model.strip():
        return replace(cfg, model=model.strip())
    return cfg


def resolve_models(settings: dict[str, Any], *, env_path: Path | None = None) -> list[LLMConfig]:
    """Return ordered, deduplicated primary and fallback connections.

    Accept either full profile settings or their ``models`` subsection. Legacy
    routing stays intact unless ``tiered_enabled is True``. Model overrides are
    literal API model IDs supplied by the user, never inferred from agent names.
    ``env_path`` selects an explicit config file; ambient env precedence is the
    existing LLMConfig behavior.
    """
    values = _model_settings(settings)
    tiered = values.get('tiered_enabled') is True
    primary_name = values.get('primary_provider', 'default') if tiered else 'default'
    fallback_name = 'default' if primary_name == 'ds_v4_flash' else 'ds_v4_flash'
    primary = _provider(primary_name, env_path)
    if tiered:
        primary = _override_model(primary, values.get('primary_model'))
    configs = [primary, _provider(fallback_name, env_path)]
    result: list[LLMConfig] = []
    seen: set[str] = set()
    for cfg in configs:
        if cfg is not None and (identity := _identity(cfg)) not in seen:
            seen.add(identity)
            result.append(cfg)
    return result


def resolve_review_model(settings: dict[str, Any], *, env_path: Path | None = None) -> LLMConfig | None:
    """Load the separately opted-in review connection; otherwise read nothing."""
    values = _model_settings(settings)
    if values.get('review_enabled') is not True:
        return None
    cfg = _provider(values.get('review_provider', 'ds_v4_flash'), env_path)
    return _override_model(cfg, values.get('review_model'))


class CircuitBreaker:
    """SQLite breaker shared by processes using the same dedicated db path.

    A cooled-down open endpoint grants a single leased probe. A timed-out or
    crashed probe can be retried after its lease expires. ``success``/``failure``
    must be called on the same breaker instance that granted a probe. Normal
    closed requests may run concurrently; successes clear accumulated failures.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._probe_tokens: dict[str, str] = {}
        self._probe_lock = threading.Lock()
        with self._transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS model_health (
                identity TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                failure_count INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'closed',
                open_until REAL NOT NULL DEFAULT 0,
                threshold INTEGER NOT NULL DEFAULT 3,
                cooldown REAL NOT NULL DEFAULT 300,
                probe_until REAL NOT NULL DEFAULT 0,
                probe_token TEXT NOT NULL DEFAULT ''
            )''')

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def permit(self, cfg: LLMConfig, *, threshold: int = 3,
               cooldown: float = 300, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else float(now)
        threshold = max(1, int(threshold))
        cooldown = max(0.0, float(cooldown))
        identity = _identity(cfg)
        with self._transaction() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO model_health(identity, model) VALUES (?, ?)',
                (identity, cfg.model),
            )
            row = conn.execute('SELECT * FROM model_health WHERE identity=?', (identity,)).fetchone()
            if row['state'] == 'closed':
                conn.execute('UPDATE model_health SET threshold=?, cooldown=? WHERE identity=?',
                             (threshold, cooldown, identity))
                return True
            if row['state'] == 'open' and timestamp < row['open_until']:
                return False
            if row['state'] == 'half_open' and timestamp < row['probe_until']:
                return False
            token = uuid.uuid4().hex
            # Keep a lease beyond the request timeout, with a bounded recovery
            # delay for crashed callers even when timeout config is excessive.
            lease = min(120.0, max(60.0, float(cfg.timeout_seconds) + 5.0))
            conn.execute('''UPDATE model_health SET state='half_open', probe_until=?,
                probe_token=?, threshold=?, cooldown=? WHERE identity=?''',
                         (timestamp + lease, token, threshold, cooldown, identity))
            with self._probe_lock:
                self._probe_tokens[identity] = token
            return True

    def _owns_probe(self, identity: str, row: sqlite3.Row) -> bool:
        with self._probe_lock:
            return self._probe_tokens.get(identity) == row['probe_token']

    def _forget_probe(self, identity: str) -> None:
        with self._probe_lock:
            self._probe_tokens.pop(identity, None)

    def success(self, cfg: LLMConfig, *, now: float | None = None) -> None:
        identity = _identity(cfg)
        with self._transaction() as conn:
            row = conn.execute('SELECT * FROM model_health WHERE identity=?', (identity,)).fetchone()
            if row is None or row['state'] == 'open' or (row['state'] == 'half_open' and not self._owns_probe(identity, row)):
                return
            conn.execute('''UPDATE model_health SET failure_count=0, state='closed',
                open_until=0, probe_until=0, probe_token='' WHERE identity=?''', (identity,))
            self._forget_probe(identity)

    def failure(self, cfg: LLMConfig, *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        identity = _identity(cfg)
        with self._transaction() as conn:
            row = conn.execute('SELECT * FROM model_health WHERE identity=?', (identity,)).fetchone()
            if row is None or (row['state'] == 'half_open' and not self._owns_probe(identity, row)):
                return
            failures = row['failure_count'] + 1
            opened = row['state'] != 'closed' or failures >= row['threshold']
            conn.execute('''UPDATE model_health SET failure_count=?, state=?,
                open_until=?, probe_until=0, probe_token='' WHERE identity=?''',
                         (failures, 'open' if opened else 'closed',
                          timestamp + row['cooldown'] if opened else 0, identity))
            self._forget_probe(identity)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return safe health details without URLs, keys, or endpoint digests."""
        with self._transaction() as conn:
            rows = conn.execute('''SELECT model, failure_count, state, open_until
                FROM model_health ORDER BY model, identity''').fetchall()
            return [dict(row) for row in rows]

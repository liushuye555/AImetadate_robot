from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from qq_onebot_whitelist import knowledge_models as models
from qq_onebot_whitelist.llm_summary import LLMConfig


@pytest.fixture
def configs(monkeypatch):
    primary = LLMConfig('https://primary.test/v1?private=secret-url', 'private-primary-key', 'primary')
    fallback = LLMConfig('https://fallback.test/v1', 'private-fallback-key', 'fallback')
    calls = []
    monkeypatch.setattr(LLMConfig, 'from_env', lambda: calls.append(('default', None)) or primary)
    monkeypatch.setattr(LLMConfig, 'from_env_file', lambda path: calls.append(('default', path)) or primary)
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file', lambda path=None: calls.append(('ds', path)) or fallback)
    return primary, fallback, calls


def test_default_routing_preserves_primary_fallback_and_ignores_overrides(configs):
    primary, fallback, calls = configs
    assert models.resolve_models({'models': {'primary_provider': 'ds_v4_flash', 'primary_model': 'cheap'}}) == [primary, fallback]
    assert calls == [('default', None), ('ds', None)]


@pytest.mark.parametrize('enabled', [False, None, 'true', 1])
def test_opt_ins_require_boolean_true(configs, enabled):
    primary, fallback, calls = configs
    settings = {'tiered_enabled': enabled, 'review_enabled': enabled, 'primary_model': 'cheap'}
    assert models.resolve_review_model(settings) is None
    assert calls == []
    assert models.resolve_models(settings) == [primary, fallback]


def test_tiered_override_uses_configured_connection_and_explicit_model(configs):
    primary, fallback, _ = configs
    resolved = models.resolve_models({'models': {'tiered_enabled': True, 'primary_model': ' user-model '}})
    assert resolved[0].model == 'user-model'
    assert resolved[0].api_key == primary.api_key
    assert resolved[0].base_url == primary.base_url
    assert primary.model == 'primary'
    assert resolved[1] is fallback


def test_tiered_provider_selection_reorders_fallback(configs):
    primary, fallback, _ = configs
    assert models.resolve_models({'tiered_enabled': True, 'primary_provider': 'ds_v4_flash'}) == [fallback, primary]


def test_explicit_env_path_and_review_resolution(configs, tmp_path):
    primary, fallback, calls = configs
    env = tmp_path / 'fake.env'
    assert models.resolve_models({}, env_path=env) == [primary, fallback]
    review = models.resolve_review_model({'review_enabled': True, 'review_model': 'review-user-id'}, env_path=env)
    assert review.model == 'review-user-id'
    assert review.api_key == fallback.api_key
    assert calls == [('default', env), ('ds', env), ('ds', env)]
    assert not env.exists()


def test_review_empty_model_preserves_connection_model(configs):
    _, fallback, _ = configs
    assert models.resolve_review_model({'review_enabled': True, 'review_model': ''}) is fallback


def test_explicit_empty_review_provider_inherits_primary(configs):
    primary, _, _ = configs
    assert models.resolve_review_model({'review_enabled': True, 'review_provider': ''}) is primary


def test_missing_connections_and_duplicate_identity(monkeypatch):
    primary = LLMConfig('https://api.deepseek.com', 'key', 'same')
    duplicate = LLMConfig('https://api.deepseek.com/v1/', 'key', 'same')
    monkeypatch.setattr(LLMConfig, 'from_env', lambda: primary)
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file', lambda path=None: duplicate)
    assert models.resolve_models({}) == [primary]
    monkeypatch.setattr(LLMConfig, 'from_env', lambda: None)
    assert models.resolve_models({}) == [duplicate]
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file', lambda path=None: None)
    assert models.resolve_models({}) == []
    assert models.resolve_review_model({'review_enabled': True}) is None


def test_unsupported_provider_is_not_interpreted_as_agent_model(configs):
    with pytest.raises(ValueError, match='supported model providers'):
        models.resolve_models({'tiered_enabled': True, 'primary_provider': 'gpt-6-astra'})


def test_failures_open_skip_primary_and_allow_fallback(tmp_path, configs):
    primary, fallback, _ = configs
    breaker = models.CircuitBreaker(tmp_path / 'knowledge-model-health.db')
    for t in range(3):
        assert breaker.permit(primary, threshold=3, cooldown=10, now=t)
        breaker.failure(primary, now=t)
    assert not breaker.permit(primary, now=11)
    assert breaker.permit(fallback, now=11)
    assert breaker.snapshot() == [
        {'model': 'fallback', 'failure_count': 0, 'state': 'closed', 'open_until': 0.0},
        {'model': 'primary', 'failure_count': 3, 'state': 'open', 'open_until': 12.0},
    ]


def test_success_resets_closed_failures(tmp_path, configs):
    primary, _, _ = configs
    breaker = models.CircuitBreaker(tmp_path / 'health.db')
    assert breaker.permit(primary, now=1)
    breaker.failure(primary, now=1)
    breaker.success(primary, now=2)
    assert breaker.snapshot()[0]['failure_count'] == 0


def test_persisted_open_state_single_probe_and_recovery(tmp_path, configs):
    primary, _, _ = configs
    db = tmp_path / 'health.db'
    first, second = models.CircuitBreaker(db), models.CircuitBreaker(db)
    assert first.permit(primary, threshold=1, cooldown=10, now=0)
    first.failure(primary, now=0)
    assert not second.permit(primary, now=9)
    assert first.permit(primary, now=10)
    assert not second.permit(primary, now=10)
    second.success(primary, now=11)  # A non-owner cannot close the probe.
    assert first.snapshot()[0]['state'] == 'half_open'
    first.success(primary, now=11)
    assert second.permit(primary, now=11)
    assert second.snapshot()[0] == {'model': 'primary', 'failure_count': 0, 'state': 'closed', 'open_until': 0.0}


def test_half_open_failure_reopens_with_current_cooldown(tmp_path, configs):
    primary, _, _ = configs
    breaker = models.CircuitBreaker(tmp_path / 'health.db')
    assert breaker.permit(primary, threshold=1, cooldown=10, now=0)
    breaker.failure(primary, now=0)
    assert breaker.permit(primary, cooldown=20, now=10)
    breaker.failure(primary, now=11)
    assert breaker.snapshot()[0] == {'model': 'primary', 'failure_count': 2, 'state': 'open', 'open_until': 31.0}
    assert not breaker.permit(primary, now=30)
    assert breaker.permit(primary, now=31)


def test_crashed_probe_lease_expires_and_stale_owner_cannot_close(tmp_path, configs):
    primary, _, _ = configs
    first, second = models.CircuitBreaker(tmp_path / 'health.db'), models.CircuitBreaker(tmp_path / 'health.db')
    assert first.permit(primary, threshold=1, cooldown=10, now=0)
    first.failure(primary, now=0)
    assert first.permit(primary, now=10)
    assert not second.permit(primary, now=74)
    assert second.permit(primary, now=75)
    first.success(primary, now=76)
    first.failure(primary, now=76)
    assert second.snapshot()[0]['state'] == 'half_open'
    second.success(primary, now=77)
    assert second.snapshot()[0]['state'] == 'closed'


def test_simultaneous_probe_claims_are_atomic_across_instances(tmp_path, configs):
    primary, _, _ = configs
    first, second = models.CircuitBreaker(tmp_path / 'health.db'), models.CircuitBreaker(tmp_path / 'health.db')
    assert first.permit(primary, threshold=1, cooldown=0, now=0)
    first.failure(primary, now=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda breaker: breaker.permit(primary, now=0), [first, second]))
    assert sorted(results) == [False, True]


def test_concurrent_closed_failures_accumulate_atomically(tmp_path, configs):
    primary, _, _ = configs
    first, second = models.CircuitBreaker(tmp_path / 'health.db'), models.CircuitBreaker(tmp_path / 'health.db')
    assert first.permit(primary, threshold=2, now=0)
    assert second.permit(primary, threshold=2, now=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda breaker: breaker.failure(primary, now=1), [first, second]))
    assert first.snapshot()[0]['failure_count'] == 2
    assert first.snapshot()[0]['state'] == 'open'


def test_health_storage_and_snapshot_do_not_disclose_connections(tmp_path, configs):
    primary, _, _ = configs
    db = tmp_path / 'health.db'
    breaker = models.CircuitBreaker(db)
    assert breaker.permit(primary, threshold=1, now=0)
    breaker.failure(primary, now=0)
    snapshot = json.dumps(breaker.snapshot())
    assert set(breaker.snapshot()[0]) == {'model', 'failure_count', 'state', 'open_until'}
    stored = db.read_bytes()
    for secret in [primary.api_key, primary.base_url, 'secret-url']:
        assert secret not in snapshot
        assert secret.encode() not in stored
    with sqlite3.connect(db) as conn:
        identity = conn.execute('SELECT identity FROM model_health').fetchone()[0]
    assert len(identity) == 64
    assert identity not in snapshot


def test_credential_change_does_not_share_failed_health(tmp_path, configs):
    primary, _, _ = configs
    breaker = models.CircuitBreaker(tmp_path / 'health.db')
    assert breaker.permit(primary, threshold=1, now=0)
    breaker.failure(primary, now=0)
    changed = LLMConfig(primary.base_url, 'rotated-key', primary.model)
    assert breaker.permit(changed, now=1)


def test_disabled_resolution_does_not_create_health_database(configs, tmp_path):
    assert models.resolve_models({'models': {'circuit_enabled': False}})
    assert list(tmp_path.iterdir()) == []

from qq_onebot_whitelist import config_bridge


def _schema(monkeypatch, data):
    # Avoid config_schema's existing provider discovery from consulting .env.
    monkeypatch.setattr(config_bridge, '_env_providers', lambda: {})
    return {item['key']: item for item in config_bridge.config_schema(data)}


def test_knowledge_schema_defaults_closed(monkeypatch):
    fields = _schema(monkeypatch, {})

    assert fields['knowledge.enabled']['kind'] == 'bool'
    assert fields['knowledge.enabled']['default'] is False
    assert fields['knowledge.defaults.match_mode']['default'] == 'hybrid'
    assert fields['knowledge.defaults.topics']['default'] == []
    assert fields['knowledge.defaults.interval_minutes']['default'] == 15
    assert (fields['knowledge.defaults.interval_minutes']['min'], fields['knowledge.defaults.interval_minutes']['max']) == (1, 1440)
    assert fields['knowledge.defaults.min_new_messages']['default'] == 30
    assert (fields['knowledge.defaults.min_new_messages']['min'], fields['knowledge.defaults.min_new_messages']['max']) == (1, 200)
    assert fields['knowledge.defaults.max_wait_minutes']['default'] == 60
    assert (fields['knowledge.defaults.max_wait_minutes']['min'], fields['knowledge.defaults.max_wait_minutes']['max']) == (1, 1440)
    assert fields['knowledge.defaults.batch_size']['default'] == 100
    assert (fields['knowledge.defaults.batch_size']['min'], fields['knowledge.defaults.batch_size']['max']) == (5, 200)
    assert fields['knowledge.defaults.max_tokens_per_day']['default'] == 50000
    assert (fields['knowledge.defaults.max_tokens_per_day']['min'], fields['knowledge.defaults.max_tokens_per_day']['max']) == (1000, 10000000)
    assert fields['knowledge.defaults.files.max_file_mb']['default'] == 512
    assert fields['knowledge.defaults.files.budget_gb']['default'] == 20


def test_knowledge_switch_does_not_change_existing_feature_fields(monkeypatch):
    existing = {
        'features': {'ai_context': True, 'daily_report': False},
        'ai_context': {'enabled': True},
        'daily_report': {'enabled': False},
    }
    disabled = _schema(monkeypatch, {**existing, 'knowledge': {'enabled': False}})
    enabled = _schema(monkeypatch, {**existing, 'knowledge': {'enabled': True}})

    assert disabled['knowledge.enabled']['default'] is False
    assert enabled['knowledge.enabled']['default'] is True
    for key in ('features.ai_context', 'features.daily_report'):
        assert enabled[key]['default'] == disabled[key]['default']
    assert enabled['features.ai_context']['default'] is True
    assert enabled['features.daily_report']['default'] is False

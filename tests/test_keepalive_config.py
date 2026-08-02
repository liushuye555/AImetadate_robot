from qq_onebot_whitelist.config import load_config


def test_keepalive_config_is_explicit_and_disabled_by_default(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('keepalive:\n  enabled: true\n  interval_minutes: 30\n  groups: ["123"]\n', encoding='utf-8')
    config = load_config(path)
    assert config.keepalive_enabled is True
    assert config.keepalive_interval_minutes == 30
    assert config.keepalive_groups == {'123'}

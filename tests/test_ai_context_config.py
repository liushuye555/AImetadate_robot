from qq_onebot_whitelist.config import load_config


def test_load_config_ai_context_defaults_and_ds_all_groups(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
listen:
  blocked_groups:
    - "100000001"
ai_context:
  enabled: true
  provider: ds_v4_flash
  scopes: all_groups
  chunk_size: 200
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.ai_context_enabled is True
    assert cfg.ai_context_provider == 'ds_v4_flash'
    assert cfg.ai_context_scopes == 'all_groups'
    assert cfg.ai_context_chunk_size == 200
    assert cfg.blocked_groups == {'100000001'}

from qq_onebot_whitelist.config import load_config


def test_load_config_ai_context_auto_fields(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
ai_context:
  enabled: true
  provider: ds_v4_flash
  scopes: all_groups
  chunk_size: 200
  auto_interval_minutes: 15
  min_new_messages: 300
  allowed_windows:
    - "00:30-08:30"
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.ai_context_auto_interval_minutes == 15
    assert cfg.ai_context_min_new_messages == 300
    assert cfg.ai_context_allowed_windows == ['00:30-08:30']

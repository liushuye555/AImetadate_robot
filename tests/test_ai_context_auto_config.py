from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.onebot import ai_retry_delay_seconds


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
  allowed_windows: []
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.ai_context_auto_interval_minutes == 15
    assert cfg.ai_context_min_new_messages == 300
    assert cfg.ai_context_allowed_windows == []


def test_load_config_custom_ai_provider(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''ai_context:\n  provider: local\n  providers:\n    local:\n      base_url: http://localhost:8000/v1\n      model: qwen\n      api_key_env: LOCAL_API_KEY\n''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.ai_context_provider == 'local'
    assert cfg.ai_context_providers['local']['model'] == 'qwen'


def test_ai_retry_delay_grows_but_is_capped():
    assert ai_retry_delay_seconds(1) == 900
    assert ai_retry_delay_seconds(2) == 1800
    assert ai_retry_delay_seconds(3) == 3600
    assert ai_retry_delay_seconds(10) == 3600

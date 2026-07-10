from qq_onebot_whitelist.config import load_config


def test_load_config_startup_history(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
onebot:
  ws_url: ws://127.0.0.1:3001
startup_history:
  enabled: true
  groups:
    - "100000002"
  pages: 2
  count: 10
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.startup_history_enabled is True
    assert cfg.startup_history_groups == {'100000002'}
    assert cfg.startup_history_pages == 2
    assert cfg.startup_history_count == 10

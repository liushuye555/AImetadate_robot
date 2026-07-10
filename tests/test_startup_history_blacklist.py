from qq_onebot_whitelist.config import load_config


def test_load_config_startup_history_blacklist_mode(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
onebot:
  ws_url: ws://127.0.0.1:3001
listen:
  blocked_groups:
    - "100000001"
startup_history:
  enabled: true
  mode: blacklist
  pages: 2
  count: 10
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.startup_history_mode == 'blacklist'
    assert cfg.blocked_groups == {'100000001'}
    assert cfg.startup_history_groups == set()

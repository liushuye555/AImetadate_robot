from qq_onebot_whitelist.config import load_config


def test_load_config_startup_history_all_mode(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
startup_history:
  enabled: true
  mode: blacklist
  all: true
  max_pages: 200
  count: 50
''', encoding='utf-8')
    cfg = load_config(path)
    assert cfg.startup_history_all is True
    assert cfg.startup_history_max_pages == 200
    assert cfg.startup_history_count == 50

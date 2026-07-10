from qq_onebot_whitelist.config import load_config


def test_load_config_group_blacklist_and_image_budget(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('''
onebot:
  ws_url: ws://127.0.0.1:3001
listen:
  blocked_groups:
    - "100000001"
reply:
  whitelist_users:
    - "200000001"
images:
  max_archive_mb: 500
  candidate_ttl_hours: 24
''', encoding='utf-8')

    cfg = load_config(config_path)

    assert cfg.blocked_groups == {'100000001'}
    assert cfg.max_archive_mb == 500
    assert cfg.candidate_ttl_hours == 24

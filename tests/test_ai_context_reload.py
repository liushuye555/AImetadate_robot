from datetime import datetime

from qq_onebot_whitelist.onebot import should_run_ai_context
from qq_onebot_whitelist.settings import write_analysis_windows
from qq_onebot_whitelist.store import Store


def test_ai_context_decision_reloads_allowed_windows(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('''
storage:
  data_dir: "data"
ai_context:
  scopes: ["group:1"]
  min_new_messages: 1
  allowed_windows: []
''', encoding='utf-8')
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_message(scope='group:1', user_id='u', text='pending', raw={'message_id': 1})

    allowed, pending, _ = should_run_ai_context(config_path, store, datetime(2026, 7, 10, 15, 0))
    assert allowed is True
    assert pending == 1

    write_analysis_windows(config_path, ['00:30-08:30'])
    allowed, pending, _ = should_run_ai_context(config_path, store, datetime(2026, 7, 10, 15, 0))
    assert allowed is False
    assert pending == 1

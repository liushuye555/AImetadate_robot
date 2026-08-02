import json

from qq_onebot_whitelist import ai_context_analyze
from qq_onebot_whitelist.store import Store


def test_analyze_scope_stores_quality_without_second_llm_call(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    config.write_text('''
storage:
  data_dir: data
ai_context:
  enabled: true
  provider: ds_v4_flash
  scopes: ["group:1"]
  chunk_size: 10
''', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_message(scope='group:1', user_id='u', text='分享 ComfyUI 工作流参数', raw={'message_id': 1})
    store.record_image(
        scope='group:1',
        user_id='u',
        result={'sha256': 'a', 'retention_reason': 'positive_feedback', 'has_ai_metadata': False, 'kept_path': 'saved.png'},
        raw={'message_db_id': 1},
    )
    calls = []
    monkeypatch.setattr(ai_context_analyze, 'llm_configs_for_provider', lambda provider: (type('Cfg', (), {'model': 'test-model'})(), None))

    def summarize(records, primary, fallback):
        calls.append(records)
        assert records[0]['target_image'] is True
        return '## 工作流与参数\n包含 ComfyUI 工作流参数。'

    monkeypatch.setattr(ai_context_analyze, 'summarize_records_with_fallback', summarize)

    assert ai_context_analyze.analyze_scope(str(config), scope='group:1') == 1
    batches = store.recent_ai_context_batches(scope='group:1')
    raw = json.loads(batches[0]['raw_json'])
    assert len(calls) == 1
    assert batches[0]['summary'] == '## 工作流与参数\n包含 ComfyUI 工作流参数。'
    assert raw['quality']['value_level'] == 'high'


def test_empty_image_context_only_advances_cursor(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    config.write_text('''
storage:
  data_dir: data
ai_context:
  enabled: true
  provider: ds_v4_flash
  scopes: ["group:1"]
  chunk_size: 10
''', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_message(scope='group:1', user_id='u', text='今天吃什么', raw={'message_id': 1})
    store.record_image(
        scope='group:1',
        user_id='u',
        result={'sha256': 'a', 'retention_reason': 'nearby_ai_context', 'has_ai_metadata': False, 'kept_path': 'saved.png'},
        raw={'message_db_id': 1},
    )
    monkeypatch.setattr(ai_context_analyze, 'llm_configs_for_provider', lambda provider: (type('Cfg', (), {'model': 'm'})(), None))
    monkeypatch.setattr(ai_context_analyze, 'summarize_records_with_fallback', lambda *args: 'NO_REUSABLE_IMAGE_CONTEXT')

    assert ai_context_analyze.analyze_scope(str(config), scope='group:1') == 1

    batch = store.recent_ai_context_batches(scope='group:1')[0]
    raw = json.loads(batch['raw_json'])
    assert batch['summary'] == ''
    assert raw['hidden'] is True
    assert store.last_ai_context_end_message_id('group:1') == 1


def test_scope_without_target_image_advances_without_llm_call(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    config.write_text('''
storage:
  data_dir: data
ai_context:
  enabled: true
  provider: ds_v4_flash
  scopes: ["group:1"]
  chunk_size: 10
''', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_message(scope='group:1', user_id='u', text='普通聊天', raw={'message_id': 1})
    monkeypatch.setattr(ai_context_analyze, 'llm_configs_for_provider', lambda provider: (type('Cfg', (), {'model': 'm'})(), None))
    calls = []
    monkeypatch.setattr(ai_context_analyze, 'summarize_records_with_fallback', lambda *args: calls.append(args))

    assert ai_context_analyze.analyze_scope(str(config), scope='group:1') == 1

    assert calls == []
    assert store.last_ai_context_end_message_id('group:1') == 1
    assert json.loads(store.recent_ai_context_batches(scope='group:1')[0]['raw_json'])['hidden'] is True

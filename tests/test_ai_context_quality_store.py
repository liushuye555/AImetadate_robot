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
    calls = []
    monkeypatch.setattr(ai_context_analyze, 'llm_configs_for_provider', lambda provider: (type('Cfg', (), {'model': 'test-model'})(), None))

    def summarize(records, primary, fallback):
        calls.append(records)
        return '## 本批概览\n包含 ComfyUI 工作流参数。\n## 内容判定\nAI相关：是\n价值等级：高\n判断理由：可复用'

    monkeypatch.setattr(ai_context_analyze, 'summarize_records_with_fallback', summarize)

    assert ai_context_analyze.analyze_scope(str(config), scope='group:1') == 1
    batches = store.recent_ai_context_batches(scope='group:1')
    raw = json.loads(batches[0]['raw_json'])
    assert len(calls) == 1
    assert batches[0]['summary'] == '## 本批概览\n包含 ComfyUI 工作流参数。'
    assert raw['quality']['value_level'] == 'high'

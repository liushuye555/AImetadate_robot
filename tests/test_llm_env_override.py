from pathlib import Path

from qq_onebot_whitelist.llm_summary import LLMConfig


def test_env_model_can_override_env_file_key(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text('''
set "HUANYAN_BASE_URL=https://api.huanyan.fun/v1"
set "HUANYAN_API_KEY=file-key"
set "HUANYAN_MODEL=qwen/qwen3-next-80b-a3b-instruct"
''', encoding='utf-8')
    monkeypatch.delenv('HUANYAN_BASE_URL', raising=False)
    monkeypatch.delenv('HUANYAN_API_KEY', raising=False)
    monkeypatch.setenv('HUANYAN_MODEL', 'openai/gpt-oss-20b')
    cfg = LLMConfig.from_env_file(env_file)
    assert cfg is not None
    assert cfg.base_url == 'https://api.huanyan.fun/v1'
    assert cfg.api_key == 'file-key'
    assert cfg.model == 'openai/gpt-oss-20b'

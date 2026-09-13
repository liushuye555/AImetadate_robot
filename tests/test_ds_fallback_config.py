from pathlib import Path

from qq_onebot_whitelist.llm_summary import LLMConfig


def test_ds_fallback_config_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text('''
set "HUANYAN_BASE_URL=https://api.huanyan.fun/v1"
set "HUANYAN_API_KEY=huanyan-key"
set "HUANYAN_MODEL=qwen/qwen3-next-80b-a3b-instruct"
set "DS_V4_FLASH_BASE_URL=https://api.deepseek.com"
set "DS_V4_FLASH_API_KEY=ds-key"
set "DS_V4_FLASH_MODEL=deepseek-flash"
''', encoding='utf-8')
    monkeypatch.delenv('DS_V4_FLASH_API_KEY', raising=False)
    cfg = LLMConfig.ds_fallback_from_env_file(env_file)
    assert cfg is not None
    assert cfg.base_url == 'https://api.deepseek.com/v1'
    assert cfg.api_key == 'ds-key'
    assert cfg.model == 'deepseek-flash'

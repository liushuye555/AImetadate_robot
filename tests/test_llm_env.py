from qq_onebot_whitelist.llm_summary import LLMConfig


def test_llm_config_loads_windows_set_env_file(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('''
set "DS_V4_FLASH_BASE_URL=https://api.example.com/v1"
set "DS_V4_FLASH_API_KEY=sk-secret"
set "DS_V4_FLASH_MODEL=ds-v4-flash"
''', encoding='utf-8')
    monkeypatch.delenv('DS_V4_FLASH_BASE_URL', raising=False)
    monkeypatch.delenv('DS_V4_FLASH_API_KEY', raising=False)
    monkeypatch.delenv('DS_V4_FLASH_MODEL', raising=False)

    cfg = LLMConfig.from_env_file(env)

    assert cfg is not None
    assert cfg.base_url == 'https://api.example.com/v1'
    assert cfg.api_key == 'sk-secret'
    assert cfg.model == 'ds-v4-flash'

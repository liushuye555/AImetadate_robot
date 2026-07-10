from qq_onebot_whitelist.llm_summary import LLMConfig


def test_huanyan_is_lower_priority_than_ds_when_openrouter_missing(monkeypatch):
    monkeypatch.delenv('OPENROUTER_BASE_URL', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_MODEL', raising=False)
    monkeypatch.setenv('DS_V4_FLASH_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('DS_V4_FLASH_API_KEY', 'old')
    monkeypatch.setenv('DS_V4_FLASH_MODEL', 'deepseek-v4-flash')
    monkeypatch.setenv('HUANYAN_BASE_URL', 'https://api.huanyan.fun/v1')
    monkeypatch.setenv('HUANYAN_API_KEY', 'new')
    monkeypatch.setenv('HUANYAN_MODEL', 'qwen/qwen3-next-80b-a3b-instruct')
    cfg = LLMConfig.from_env()
    assert cfg is not None
    assert cfg.base_url == 'https://api.deepseek.com/v1'
    assert cfg.api_key == 'old'
    assert cfg.model == 'deepseek-v4-flash'

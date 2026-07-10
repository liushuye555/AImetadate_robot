from qq_onebot_whitelist.llm_summary import LLMConfig


def test_openrouter_env_takes_precedence(monkeypatch):
    monkeypatch.setenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'or-key')
    monkeypatch.setenv('OPENROUTER_MODEL', 'qwen/qwen3-next-80b-a3b-instruct:free')
    monkeypatch.setenv('HUANYAN_BASE_URL', 'https://api.huanyan.fun/v1')
    monkeypatch.setenv('HUANYAN_API_KEY', 'hy-key')
    monkeypatch.setenv('HUANYAN_MODEL', 'qwen/qwen3-next-80b-a3b-instruct')
    cfg = LLMConfig.from_env()
    assert cfg is not None
    assert cfg.base_url == 'https://openrouter.ai/api/v1'
    assert cfg.api_key == 'or-key'
    assert cfg.model == 'qwen/qwen3-next-80b-a3b-instruct:free'

from qq_onebot_whitelist import config_bridge


def test_load_env_parses_set_quoted_format(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        'set "DS_V4_FLASH_BASE_URL=https://api.deepseek.com"\n'
        'set "DS_V4_FLASH_API_KEY=sk-abc"\n'
        "# comment\n"
        "PLAIN_KEY=plain-value\n",
        encoding="utf-8",
    )
    values = config_bridge._load_env(env)
    assert values["DS_V4_FLASH_BASE_URL"] == "https://api.deepseek.com"
    assert values["DS_V4_FLASH_API_KEY"] == "sk-abc"
    assert values["PLAIN_KEY"] == "plain-value"


def test_env_providers_discovers_prefixes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        'set "DS_V4_FLASH_BASE_URL=https://x"\nset "HUANYAN_API_KEY=sk-h"\n',
        encoding="utf-8",
    )
    providers = config_bridge._env_providers()
    assert "ds_v4_flash" in providers
    assert providers["ds_v4_flash"]["api_key_env"] == "DS_V4_FLASH_API_KEY"
    assert "huanyan" in providers
    assert "openrouter" not in providers


def test_schema_provider_default_merges_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text('set "DS_V4_FLASH_API_KEY=sk-abc"\n', encoding="utf-8")
    schema = config_bridge.config_schema({"ai_context": {"provider": "ds_v4_flash"}})
    provider_field = next(item for item in schema if item["key"] == "ai_context.providers")
    assert "ds_v4_flash" in provider_field["default"]
    assert provider_field["default"]["ds_v4_flash"]["api_key_env"] == "DS_V4_FLASH_API_KEY"

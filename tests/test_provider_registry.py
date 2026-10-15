import json

import pytest
import yaml

from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.knowledge_models import resolve_models, resolve_review_model
from qq_onebot_whitelist import ai_context_analyze


def configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'ai_context': {'provider': 'freewb', 'providers': {
        'freewb': {'base_url': 'https://wb.invalid/v1', 'model': 'configured-model',
                   'api_key_env': 'TEST_FREEWB_KEY', 'timeout_seconds': 91}}}}), encoding='utf-8')
    (tmp_path / '.env').write_text('TEST_FREEWB_KEY=fictional-private-key\n', encoding='utf-8')
    return load_config(path), path


def routing(config, path, **models):
    return {'models': models, '_providers': config.ai_context_providers,
            '_default_provider': config.ai_context_provider, '_env_path': path.parent / '.env'}


def test_selected_custom_provider_used_by_knowledge_and_context_without_ds(tmp_path, monkeypatch):
    config, path = configured(tmp_path, monkeypatch)
    from qq_onebot_whitelist.llm_summary import LLMConfig
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file',
                        lambda *a: pytest.fail('custom provider must not load a DS key'))
    models = resolve_models(routing(config, path))
    assert len(models) == 1
    assert (models[0].base_url, models[0].api_key, models[0].timeout_seconds) == (
        'https://wb.invalid/v1', 'fictional-private-key', 91)
    primary, fallback = ai_context_analyze.llm_configs_for_provider('freewb', config)
    assert primary == models[0] and fallback is None
    review = resolve_review_model(routing(config, path, review_enabled=True))
    assert review == models[0]


def test_explicit_custom_primary_and_review_are_resolved(tmp_path, monkeypatch):
    config, path = configured(tmp_path, monkeypatch)
    model = resolve_models(routing(config, path, tiered_enabled=True,
        primary_provider='freewb', primary_model='custom-primary'))[0]
    assert model.model == 'custom-primary'
    review = resolve_review_model(routing(config, path, review_enabled=True,
        review_provider='freewb', review_model='custom-review'))
    assert review.model == 'custom-review' and review.api_key == model.api_key


def test_missing_custom_key_fails_without_falling_back(tmp_path, monkeypatch):
    config, path = configured(tmp_path, monkeypatch)
    (tmp_path / '.env').unlink()
    with pytest.raises(ValueError, match='TEST_FREEWB_KEY'):
        resolve_models(routing(config, path))


@pytest.mark.parametrize('name', ['default', 'ds_v4_flash'])
def test_registry_override_of_builtin_name_never_enables_ds_fallback(tmp_path, monkeypatch, name):
    config, path = configured(tmp_path, monkeypatch)
    config.ai_context_providers[name] = config.ai_context_providers.pop('freewb')
    config.ai_context_provider = name
    from qq_onebot_whitelist.llm_summary import LLMConfig
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file',
                        lambda *a: pytest.fail('saved provider must not read built-in DS credential'))
    settings = routing(config, path, review_enabled=True)
    assert len(resolve_models(settings)) == 1
    assert resolve_review_model(settings).base_url == 'https://wb.invalid/v1'


@pytest.mark.parametrize('name', ['auto', 'openrouter', 'openai_compatible', 'ds', 'deepseek'])
def test_builtin_aliases_share_the_config_local_environment(tmp_path, monkeypatch, name):
    from qq_onebot_whitelist.llm_summary import LLMConfig
    config, path = configured(tmp_path, monkeypatch)
    config.ai_context_providers = {}
    config.ai_context_provider = name
    seen = []
    fake = LLMConfig('https://example.invalid/v1', 'fake', 'fake')
    monkeypatch.setattr(LLMConfig, 'from_env_file', lambda p: seen.append(p) or fake)
    monkeypatch.setattr(LLMConfig, 'ds_fallback_from_env_file', lambda p: seen.append(p) or fake)
    assert resolve_models(routing(config, path))
    assert ai_context_analyze.llm_configs_for_provider(name, config)[0] == fake
    assert seen and all(p == path.parent / '.env' for p in seen)


def test_secret_with_blank_env_name_is_not_treated_as_a_default_provider(tmp_path, monkeypatch):
    config, path = configured(tmp_path, monkeypatch)
    config.ai_context_providers['freewb']['api_key_env'] = ''
    with pytest.raises(ValueError, match='api_key_env'):
        resolve_models(routing(config, path))


def test_saved_provider_reaches_real_knowledge_entrypoint(tmp_path, monkeypatch):
    from qq_onebot_whitelist.config_bridge import patch_config, patch_env
    from qq_onebot_whitelist import knowledge
    path = tmp_path / 'config.yaml'
    path.write_text('{}', encoding='utf-8')
    patch_config(path, {'storage': {'data_dir': str(tmp_path / 'data')},
        'ai_context': {'provider': 'freewb', 'providers': {'freewb': {
            'base_url': 'https://wb.invalid/v1', 'model': 'saved-model',
            'api_key_env': 'TEST_SAVED_WB_KEY'}}}, 'knowledge': {'enabled': True,
            'groups': {'group:123': {'enabled': True, 'summary': {'enabled': True}}}}})
    patch_env(tmp_path / '.env', {'TEST_SAVED_WB_KEY': 'fictional-persisted-key'})
    monkeypatch.chdir(tmp_path.parent)
    called = []
    def request(messages, model):
        called.append(model)
        assert model.api_key == 'fictional-persisted-key'
        assert model.base_url == 'https://wb.invalid/v1'
        return {'summary': [{'text': '已读取保存的供应商', 'evidence_ids': [1]}], 'items': [], 'terms': []}, 12
    result = knowledge.analyze(path, 'group:123', feature='summary', request=request,
        records=[{'id': 1, 'scope': 'group:123', 'text': '测试文字', 'time': None,
                  'quoted_id': None, 'quoted_text': '', 'files': [], 'links': [], 'segments': ['text']}])
    assert result['status'] == 'completed' and len(called) == 1
    assert called[0].model == 'saved-model'

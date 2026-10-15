"""Resolve a configured provider as one connection, without implicit fallbacks."""
from __future__ import annotations

import os
from pathlib import Path

from .llm_summary import LLMConfig, _read_env_values, normalize_base_url


def builtin_provider_name(name: str) -> str:
    name = name.casefold()
    if name in {'ds', 'deepseek', 'deepseek_v4_flash', 'ds_v4_flash'}:
        return 'ds_v4_flash'
    if name in {'default', 'auto', 'openrouter', 'free', 'openrouter_free', 'openai_compatible'}:
        return 'default'
    return name


def configured_provider(name: str, providers: dict, env_path: Path | None = None) -> LLMConfig | None:
    matching = next((key for key in providers if key.casefold() == name.casefold()), None)
    if matching is None:
        return None
    settings = providers[matching]
    key_name = str(settings.get('api_key_env') or '').strip()
    if not key_name:
        raise ValueError(f'AI provider {matching}: api_key_env is empty; save its API key in settings')
    values = _read_env_values(env_path or Path.cwd() / '.env')
    key = os.environ.get(key_name) or values.get(key_name)
    if not key:
        raise ValueError(f'AI provider {matching}: missing credential environment variable {key_name}')
    base_url, model = settings.get('base_url'), settings.get('model')
    if not base_url or not model:
        raise ValueError(f'AI provider {matching}: base_url and model are required')
    timeout = int(settings.get('timeout_seconds') or 60)
    if not 1 <= timeout <= 3600:
        raise ValueError(f'AI provider {matching}: invalid timeout_seconds')
    return LLMConfig(normalize_base_url(str(base_url)), key, str(model), timeout)


def routing_settings(config, models: dict) -> dict:
    """Carry the saved registry to every knowledge-model call site."""
    explicit = config.ai_context_provider_explicit or bool(config.ai_context_providers)
    return {'models': models, '_providers': config.ai_context_providers,
            '_default_provider': config.ai_context_provider if explicit else 'default',
            '_env_path': config.source_path.parent / '.env' if config.source_path and explicit else None}

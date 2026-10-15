import json
from pathlib import Path
import subprocess
import sys

import pytest

from qq_onebot_whitelist.config_bridge import config_schema, patch_env


def test_provider_schema_does_not_return_inline_credentials():
    fields = config_schema({'ai_context': {'providers': {'local': {
        'api_key': 'fictional-inline-key', 'base_url': 'https://local.invalid/v1',
        'timeout_seconds': 91}}}})
    assert 'fictional-inline-key' not in json.dumps(fields)
    providers = next(row for row in fields if row['key'] == 'ai_context.providers')['default']
    assert providers['local']['timeout_seconds'] == 91


def test_env_bridge_persists_next_to_config_without_echoing_secret(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('{}', encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'qq_onebot_whitelist.config_bridge',
        'env-patch', '--config', str(config), '--json', '-'],
        input=json.dumps({'TEST_FREEWB_KEY': 'fictional-bridge-secret'}),
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['saved'] is True
    assert 'fictional-bridge-secret' not in result.stdout + result.stderr
    assert (tmp_path / '.env').read_text(encoding='utf-8') == 'TEST_FREEWB_KEY=fictional-bridge-secret\n'
    result = subprocess.run([sys.executable, '-m', 'qq_onebot_whitelist.config_bridge',
        'env-get', '--config', str(config)], capture_output=True, text=True, check=True)
    assert 'fictional-bridge-secret' not in result.stdout
    assert json.loads(result.stdout)['TEST_FREEWB_KEY']['configured'] is True


@pytest.mark.parametrize('patch', [{'': 'lost-secret'}, {'KEY': 'one\nTWO=bad'}])
def test_invalid_environment_patch_preserves_existing_file(tmp_path, patch):
    path = tmp_path / '.env'
    path.write_text('KEEP=original\n', encoding='utf-8')
    with pytest.raises(ValueError):
        patch_env(path, patch)
    assert path.read_text(encoding='utf-8') == 'KEEP=original\n'


def test_full_provider_registry_save_actually_removes_deleted_provider(tmp_path):
    from qq_onebot_whitelist.config_bridge import patch_config
    config = tmp_path / 'config.yaml'
    config.write_text('{}', encoding='utf-8')
    patch_config(config, {'ai_context': {'provider': 'keep', 'providers': {
        'keep': {'model': 'kept'}, 'remove': {'model': 'deleted'}}}, 'knowledge': {'enabled': False}})
    result = patch_config(config, {'ai_context': {'providers': {'keep': {'model': 'new'}}}})
    assert result['ai_context']['providers'] == {'keep': {'model': 'new'}}
    assert result['ai_context']['provider'] == 'keep'
    assert result['knowledge']['enabled'] is False

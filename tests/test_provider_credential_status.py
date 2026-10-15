import json

from qq_onebot_whitelist.config_bridge import config_schema, patch_config


def test_schema_distinguishes_missing_reference_missing_key_and_configured(tmp_path, monkeypatch):
    monkeypatch.delenv('TEST_PROVIDER_CONFIGURED', raising=False)
    monkeypatch.delenv('TEST_PROVIDER_MISSING', raising=False)
    env = tmp_path / '.env'
    env.write_text('TEST_PROVIDER_CONFIGURED=fictional-status-secret\n', encoding='utf-8')
    schema = config_schema({'ai_context': {'providers': {
        'no-reference': {'api_key_env': ''},
        'no-key': {'api_key_env': 'TEST_PROVIDER_MISSING'},
        'configured': {'api_key_env': 'TEST_PROVIDER_CONFIGURED'}}}}, env_path=env)
    providers = next(row['default'] for row in schema if row['key'] == 'ai_context.providers')
    assert providers['no-reference']['_credential_status'] == 'missing_reference'
    assert providers['no-key']['_credential_status'] == 'missing_key'
    assert providers['configured']['_credential_status'] == 'configured'
    assert 'fictional-status-secret' not in json.dumps(schema)


def test_diagnostic_status_is_not_persisted_as_provider_configuration(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}', encoding='utf-8')
    result = patch_config(path, {'ai_context': {'providers': {
        'local': {'api_key_env': 'SAVED_KEY', '_credential_status': 'configured', 'custom': 'kept'}}}})
    assert result['ai_context']['providers']['local'] == {'api_key_env': 'SAVED_KEY', 'custom': 'kept'}
    assert patch_config(path, {'ai_context': {'providers': None}})['ai_context']['providers'] is None

import json

import pytest

from qq_onebot_whitelist.content_utils import redact_secrets, redacted_json


def test_workbuddy_credential_is_redacted_without_an_assignment_label():
    fictional = 'wb-' + 'a' * 64
    assert fictional not in redact_secrets('连接凭据 ' + fictional)
    assert 'workbuddy' in redact_secrets('workbuddy 日常讨论')


@pytest.mark.parametrize('text', ['password=fictional_credential_12345" next',
    'api_key="fictional_credential_12345"', '{"api_key":"fictional_credential_12345"}',
    "pwd='fictional_credential_12345' trailing"])
def test_redaction_preserves_transport_json_and_removes_quoted_credentials(text):
    result = redacted_json({'messages': [{'id': 42, 'text': text}]})
    assert json.loads(result)['messages'][0]['id'] == 42
    assert 'fictional_credential_12345' not in result
    assert '[已脱敏]' in result


def test_nested_secret_fields_are_removed_even_without_a_textual_prefix():
    value = {'payload': {'api_key': 'fictional_value', 'text': 'normal text'}, 'count': 2}
    result = json.loads(redacted_json(value))
    assert result['payload']['api_key'] == '[已脱敏]' and result['count'] == 2
    assert value['payload']['api_key'] == 'fictional_value'


def test_plain_redaction_keeps_balanced_quotes_for_embedded_json():
    text = '{"password":"fictional_credential_12345"}'
    assert json.loads(redact_secrets(text))['password'] == '[已脱敏]'

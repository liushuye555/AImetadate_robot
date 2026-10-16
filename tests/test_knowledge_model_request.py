import io
import json

import pytest

from qq_onebot_whitelist import knowledge
from qq_onebot_whitelist.llm_summary import LLMConfig


@pytest.mark.parametrize('model,thinking', [('deepseek-flash', {'type': 'disabled'}),
    ('cn:deepseek-v4.1-flash', {'type': 'disabled'}), ('other-model', None)])
def test_known_ds_endpoint_preserves_completion_allowance_for_structured_output(monkeypatch, model, thinking):
    captured = []
    def open_url(req, **kwargs):
        captured.append(json.loads(req.data))
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
                                     'usage': {'total_tokens': 9}}).encode())
    monkeypatch.setattr(knowledge.netutil, 'open_url', open_url)
    result, usage = knowledge.model_request([{'role': 'user', 'content': 'test'}],
        LLMConfig('https://model.invalid/v1', 'test-only', model))
    assert result == {} and usage == 9
    assert captured[0].get('thinking') == thinking
    assert captured[0]['max_tokens'] == knowledge.MAX_COMPLETION

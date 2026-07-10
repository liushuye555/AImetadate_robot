import urllib.error

import pytest

from qq_onebot_whitelist.llm_summary import normalize_base_url, read_http_error_body


def test_normalize_base_url_adds_v1_for_deepseek_host():
    assert normalize_base_url('https://api.deepseek.com') == 'https://api.deepseek.com/v1'
    assert normalize_base_url('https://api.deepseek.com/v1') == 'https://api.deepseek.com/v1'
    assert normalize_base_url('https://example.com/openai') == 'https://example.com/openai'

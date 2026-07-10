import json

from qq_onebot_whitelist.llm_summary import LLMConfig, filter_relevant_records, normalize_summary_output, summarize_records_with_llm


def test_filter_relevant_records_removes_empty_short_and_at_all_noise():
    records = [
        {'text': '', 'links': []},
        {'text': '[图片]', 'links': []},
        {'text': '@全体成员 大家别忘了', 'links': []},
        {'text': '课程汇报 PPT 需要在今晚前提交，文件名为姓名加题目', 'links': []},
        {'text': '资料 https://a.test', 'links': ['https://a.test']},
    ]

    filtered = filter_relevant_records(records)

    assert len(filtered) == 2
    assert '课程汇报' in filtered[0]['text']
    assert filtered[1]['links'] == ['https://a.test']


def test_summarize_records_with_llm_posts_openai_compatible_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({'choices': [{'message': {'content': '自动总结结果'}}]}).encode('utf-8')

    def fake_urlopen(req, timeout):
        captured['url'] = req.full_url
        captured['payload'] = json.loads(req.data.decode('utf-8'))
        captured['headers'] = dict(req.header_items())
        captured['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    cfg = LLMConfig(base_url='https://api.example.com/v1', api_key='sk-test', model='ds-v4-flash')
    records = [{'text': '重要：明天交作业', 'links': []}]

    result = summarize_records_with_llm(records, cfg)

    assert result == '自动总结结果'
    assert captured['url'] == 'https://api.example.com/v1/chat/completions'
    assert captured['payload']['model'] == 'ds-v4-flash'
    assert '不能只输出“无有效讨论”' in captured['payload']['messages'][0]['content']
    assert '明天交作业' in captured['payload']['messages'][1]['content']


def test_summary_redacts_secrets_and_removes_llm_preamble():
    result = normalize_summary_output('好的，已接收并分析。\n\n## 概览\n密钥 sk-abcdefghijklmnopqrstuvwxyz')

    assert result.startswith('## 概览')
    assert 'sk-abcdefghijklmnopqrstuvwxyz' not in result
    assert '[已脱敏密钥]' in result

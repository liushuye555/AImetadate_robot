import json

from qq_onebot_whitelist.commands import build_reply
from qq_onebot_whitelist.llm_summary import LLMConfig, summarize_records_with_llm
from qq_onebot_whitelist.store import Store


def test_resources_query_group_before_limit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='1', url='https://local-group.test')
    store.record_file(scope='group:1', user_id='1', file_name='own.pdf', file_size=5, url=None, kind='other', raw={})
    for i in range(30):
        store.record_link(scope='group:2', user_id='2', url=f'https://other-group.test/{i}')
        store.record_file(scope='group:2', user_id='2', file_name=f'other-{i}.pdf', file_size=5, url=None, kind='other', raw={})
    text = build_reply({'message_type': 'group', 'group_id': 1, 'message': '资源'}, store)
    assert 'local-group.test' in text and 'own.pdf' in text
    assert 'other-group' not in text and 'other-' not in text


def test_general_summary_prompt_does_not_use_image_task(monkeypatch):
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps({'choices': [{'message': {'content': '## 讨论结论\n更新依赖解决安装问题'}}]}).encode()
    def open_url(req, timeout):
        captured.update(json.loads(req.data))
        return Response()
    from qq_onebot_whitelist import netutil
    monkeypatch.setattr(netutil, 'open_url', open_url)
    cfg = LLMConfig('https://model.invalid/v1', 'key')
    result = summarize_records_with_llm([{'id': 1, 'text': '更新依赖后安装正常了'}], cfg, purpose='group_summary')
    system = captured['messages'][0]['content']
    assert '群聊总结助手' in system
    assert '不要总结聊天主题' not in system
    assert 'NO_REUSABLE_IMAGE_CONTEXT' not in system
    assert '安装问题' in result

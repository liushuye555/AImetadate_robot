from qq_onebot_whitelist.commands import build_reply
from qq_onebot_whitelist.store import Store


def test_private_resource_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'bot.db')
    store.record_file(scope='group:1', user_id='u1', file_name='a.safetensors', file_size=1024, url='u', kind='model', raw={})
    store.record_link(scope='group:1', user_id='u2', url='https://civitai.com/models/1', message_text='这个lora不错', quoted_text='', kind='civitai_model')
    event = {'message_type': 'private', 'user_id': 200000001, 'message': '资源'}

    reply = build_reply(event, store)

    assert '模型/文件' in reply
    assert 'a.safetensors' in reply
    assert 'Civitai' in reply or 'civitai' in reply

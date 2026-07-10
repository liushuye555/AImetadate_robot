from qq_onebot_whitelist.commands import build_reply, scope_for_event
from qq_onebot_whitelist.store import Store


class FakeViewBuilder:
    def __init__(self):
        self.calls = 0
    def __call__(self):
        self.calls += 1
        return {'01_AI元数据_ComfyUI': 2, '02_群友好评': 1}


def test_private_admin_refresh_without_slash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'bot.db')
    event = {'message_type': 'private', 'user_id': 200000001, 'message': '刷新'}
    builder = FakeViewBuilder()

    reply = build_reply(event, store, view_builder=builder)

    assert builder.calls == 1
    assert '分类视图已刷新' in reply
    assert '01_AI元数据_ComfyUI: 2' in reply


def test_refresh_aliases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(tmp_path / 'bot.db')
    builder = FakeViewBuilder()
    for text in ['强制刷新', '整理', '刷新分类']:
        reply = build_reply({'message_type': 'private', 'user_id': 200000001, 'message': text}, store, view_builder=builder)
        assert '分类视图已刷新' in reply
    assert builder.calls == 3

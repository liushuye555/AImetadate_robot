"""私聊合并消息收藏：保存、去重、引用/群聊不收藏、收藏夹命令。"""

import asyncio

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.store import Store


def _forward_event(*, message_type='private', reply=False, user_id='2718273234'):
    segments = []
    if reply:
        segments.append({'type': 'reply', 'data': {'id': '123'}})
    segments.append({'type': 'forward', 'data': {'id': 'f1'}})
    return {
        'post_type': 'message',
        'message_type': message_type,
        'group_id': '111' if message_type == 'group' else None,
        'user_id': user_id,
        'message': segments,
    }


def test_favorites_store_dedup(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert store.save_favorite(user_id='u1', content_hash='abc', summary='第一条') is True
    assert store.save_favorite(user_id='u1', content_hash='abc', summary='重复') is False
    assert store.save_favorite(user_id='u2', content_hash='abc', summary='别人的') is True
    favs = store.list_favorites('u1')
    assert len(favs) == 1 and favs[0]['summary'] == '第一条'


def test_private_forward_saved(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')

    async def fake_call(ws, action, params):
        if action == 'get_forward_msg':
            return {'data': {'messages': [
                {'user_id': 'u9', 'nickname': '小明', 'message': [{'type': 'text', 'data': {'text': '好东西'}}]},
            ]}}
        return {'status': 'ok'}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)
    saved = asyncio.run(favorites.maybe_save_private_forward(None, store, _forward_event(), AppConfig()))
    assert saved is True
    assert len(store.list_favorites('2718273234')) == 1


def test_reply_or_group_forward_not_saved(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')

    async def fake_call(ws, action, params):
        return {'data': {'messages': [{'user_id': 'u', 'nickname': 'n', 'message': []}]}}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)
    assert asyncio.run(favorites.maybe_save_private_forward(None, store, _forward_event(reply=True), AppConfig())) is False
    assert asyncio.run(favorites.maybe_save_private_forward(None, store, _forward_event(message_type='group'), AppConfig())) is False
    assert store.list_favorites('2718273234') == []


def test_favorites_command(tmp_path):
    from qq_onebot_whitelist.commands import build_reply

    store = Store(tmp_path / 'bot.db')
    event = {'post_type': 'message', 'message_type': 'private', 'user_id': 'u1',
             'message': [{'type': 'text', 'data': {'text': '收藏夹'}}]}
    assert '暂无收藏' in build_reply(event, store)
    store.save_favorite(user_id='u1', content_hash='x', summary='模型分享：LoRA 链接 https://a.test')
    reply = build_reply(event, store)
    assert '你的收藏' in reply and '模型分享' in reply

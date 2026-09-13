"""私聊引用合并消息后显式保存图片的行为。"""

import asyncio
import json

import websockets

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.store import Store


class FakeWs:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _save_command_event(*, text='/保存图片', reply_id='123', user_id='2718273234'):
    return {
        'post_type': 'message',
        'message_type': 'private',
        'user_id': user_id,
        'message': [
            {'type': 'reply', 'data': {'id': reply_id}},
            {'type': 'text', 'data': {'text': text}},
        ],
    }


def test_save_images_command_uses_default_folder_and_cleans_category():
    from qq_onebot_whitelist.favorites import parse_save_images_command

    assert parse_save_images_command('/保存图片') == '未分类'
    assert parse_save_images_command('保存图片   ') == '未分类'
    assert parse_save_images_command('/保存图片 工作流/测试:*') == '工作流_测试_'
    assert parse_save_images_command('收藏夹') is None


def test_private_forward_is_not_saved_automatically(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')
    event = {
        'post_type': 'message',
        'message_type': 'private',
        'user_id': 'u1',
        'message': [{'type': 'forward', 'data': {'id': 'f1'}}],
    }
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError('automatic saving must not fetch forwarded messages')

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fail_if_called)
    assert asyncio.run(favorites.maybe_save_private_forward(None, store, event, AppConfig())) is False
    assert called is False
    assert store.list_favorites('u1') == []


def test_save_replied_forward_images_saves_all_and_deduplicates_by_category(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')
    config = AppConfig(data_dir=tmp_path / 'data')
    monkeypatch.setattr(websockets, 'connect', lambda url: FakeWs())
    calls = []

    async def fake_call(ws, action, params):
        calls.append((action, params))
        if action == 'get_msg':
            return {'data': {'message': [{'type': 'forward', 'data': {'id': 'f1'}}]}}
        if action == 'get_forward_msg':
            return {'data': {'messages': [
                {'user_id': 'u9', 'nickname': '小明', 'message': [
                    {'type': 'image', 'data': {'url': 'https://img.test/one.png', 'file': 'one.png'}},
                    {'type': 'image', 'data': {'url': 'https://img.test/two.png', 'file': 'two.png'}},
                ]},
                {'user_id': 'u8', 'nickname': '小红', 'message': [
                    {'type': 'image', 'data': {'url': 'https://img.test/one.png', 'file': 'one-again.png'}},
                    {'type': 'image', 'data': {'url': 'https://img.test/three.png', 'file': 'three.png'}},
                ]},
            ]}}
        raise AssertionError(action)

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)

    def fake_process(url, **kwargs):
        calls.append(('download', url, kwargs))
        digest = {'one.png': 'a' * 64, 'two.png': 'b' * 64, 'three.png': 'c' * 64}[url.rsplit('/', 1)[-1]]
        return {
            'url': url, 'sha256': digest, 'size': 100, 'format': 'PNG',
            'width': 100, 'height': 200, 'metadata_keys': [],
            'has_ai_metadata': False, 'ai_source': '', 'text_excerpt': '',
            'kept_path': str(tmp_path / f'{digest}.png'),
            'retention_reason': 'chat_record_saved',
        }

    monkeypatch.setattr(favorites, 'process_image_url', fake_process)

    result = asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(text='/保存图片 旅行收藏'), config,
    ))

    assert result == {
        'ok': True, 'category': '旅行收藏', 'found': 4,
        'saved': 3, 'duplicates': 1, 'failed': 0,
    }
    with store.path.open('rb') as f:
        assert b'chat_record_saved' in f.read()  # sanity: database is non-empty binary
    rows = store.saved_image_records('2718273234', category='旅行收藏')
    assert len(rows) == 3
    assert {row['saved_category'] for row in rows} == {'旅行收藏'}
    assert all(row['retention_reason'] == 'chat_record_saved' for row in rows)
    assert all(call[2].get('force_keep') is True for call in calls if call[0] == 'download')

    again = asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(text='/保存图片 旅行收藏'), config,
    ))
    assert again['found'] == 4
    assert again['saved'] == 0
    assert again['duplicates'] == 4


def test_save_replied_forward_requires_private_reply_and_forward(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')
    config = AppConfig(data_dir=tmp_path / 'data')
    monkeypatch.setattr(websockets, 'connect', lambda url: FakeWs())

    assert asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(reply_id=''), config,
    ))['error'] == 'reply_required'
    assert asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(text='/保存图片', user_id='u1') | {'message_type': 'group'}, config,
    ))['error'] == 'private_only'

    async def no_forward_call(ws, action, params):
        return {'data': {'message': [{'type': 'text', 'data': {'text': '普通消息'}}]}}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', no_forward_call)
    result = asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(), config,
    ))
    assert result['error'] == 'forward_required'
    assert result['found'] == result['saved'] == result['duplicates'] == result['failed'] == 0


def test_saved_images_are_separate_view_categories(tmp_path):
    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / 'data'
    store = Store(data / 'bot.db')
    image = data / 'images' / 'ai' / 'aa' / ('a' * 64 + '.png')
    image.parent.mkdir(parents=True)
    image.write_bytes(b'not-a-real-image')
    store.record_image(
        scope='private:u1', user_id='u1',
        result={
            'url': 'https://img.test/a.png', 'sha256': 'a' * 64, 'size': 10,
            'format': 'PNG', 'width': 100, 'height': 200,
            'kept_path': str(image), 'retention_reason': 'chat_record_saved',
            'saved_category': '旅行收藏',
        },
        raw={'forward_id': 'f1'},
    )

    counts = build_view(tmp_path)
    assert counts['06_聊天记录收藏/旅行收藏'] == 1
    saved_dir = data / 'view' / '06_聊天记录收藏' / '旅行收藏'
    assert next(saved_dir.glob('*.png')).exists()
    assert (data / 'view' / '06_聊天记录收藏' / 'index.html').exists()
    assert '旅行收藏' in (data / 'view' / '06_聊天记录收藏' / 'index.html').read_text(encoding='utf-8')


def test_save_replied_forward_images_recurses_nested_forwards_and_avoids_cycles(tmp_path, monkeypatch):
    from qq_onebot_whitelist import favorites

    store = Store(tmp_path / 'bot.db')
    config = AppConfig(data_dir=tmp_path / 'data')
    monkeypatch.setattr(websockets, 'connect', lambda url: FakeWs())
    fetched_ids = []

    async def fake_call(ws, action, params):
        if action == 'get_msg':
            return {'data': {'message': [{'type': 'forward', 'data': {'id': 'outer'}}]}}
        if action == 'get_forward_msg':
            forward_id = params['id']
            fetched_ids.append(forward_id)
            rows = {
                'outer': [
                    {'user_id': 'u1', 'message': [
                        {'type': 'image', 'data': {'url': 'https://img.test/outer.png'}},
                        {'type': 'forward', 'data': {'id': 'inner'}},
                    ]},
                ],
                'inner': [
                    {'user_id': 'u2', 'content': [
                        {'type': 'image', 'data': {'url': 'https://img.test/inner.png'}},
                        {'type': 'forward', 'data': {'id': 'outer'}},
                    ]},
                ],
            }[forward_id]
            return {'data': {'messages': rows}}
        raise AssertionError(action)

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)

    def fake_process(url, **kwargs):
        digest = {'outer.png': 'd' * 64, 'inner.png': 'e' * 64}[url.rsplit('/', 1)[-1]]
        return {
            'url': url, 'sha256': digest, 'size': 100, 'format': 'PNG',
            'width': 100, 'height': 200, 'metadata_keys': [],
            'has_ai_metadata': False, 'ai_source': '', 'text_excerpt': '',
            'kept_path': str(tmp_path / f'{digest}.png'),
        }

    monkeypatch.setattr(favorites, 'process_image_url', fake_process)
    result = asyncio.run(favorites.save_replied_forward_images(
        store, _save_command_event(text='/保存图片 嵌套收藏'), config,
    ))

    assert result == {
        'ok': True, 'category': '嵌套收藏', 'found': 2,
        'saved': 2, 'duplicates': 0, 'failed': 0,
    }
    assert fetched_ids == ['outer', 'inner']
    rows = store.saved_image_records('2718273234', category='嵌套收藏')
    assert {row['raw']['forward_id'] for row in rows} == {'outer', 'inner'}

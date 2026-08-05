"""聊天：记忆条数、冷却、LLM 回复入库。"""

import json

from qq_onebot_whitelist import chat
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.store import Store


def make_config(**over):
    base = dict(
        chat_enabled=True,
        chat_persona='你是猫娘',
        chat_memory_turns=10,
        chat_admin_memory_turns=50,
        chat_cooldown_seconds=1,
    )
    base.update(over)
    return AppConfig(**base)


def test_recent_chat_turns_last_n_in_order(tmp_path):
    store = Store(tmp_path / 'bot.db')
    for i in range(5):
        store.record_chat_turn('group:1', 'u1', 'user', f'q{i}')
        store.record_chat_turn('group:1', 'u1', 'bot', f'a{i}')
    turns = store.recent_chat_turns('group:1', 'u1', 4)
    assert [t['text'] for t in turns] == ['q3', 'a3', 'q4', 'a4']
    assert store.recent_chat_turns('group:1', 'other', 4) == []


def test_cooldown_blocks_repeat_same_user():
    cfg = make_config(chat_cooldown_seconds=5)
    assert chat._cooldown_ok(cfg, 'group:1', 'u1') is True
    assert chat._cooldown_ok(cfg, 'group:1', 'u1') is False
    assert chat._cooldown_ok(cfg, 'group:1', 'u2') is True


def test_chat_reply_roundtrip(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({'choices': [{'message': {'content': '喵~ 你好呀'}}]}).encode('utf-8')

    monkeypatch.setattr(chat.netutil, 'open_url', lambda req, timeout=None: FakeResp())
    cfg = make_config()
    event = {
        'post_type': 'message', 'message_type': 'private', 'user_id': '2718273234',
        'message': [{'type': 'text', 'data': {'text': '你好'}}],
    }
    reply = chat.maybe_chat_reply(store, event, cfg)
    assert reply == '喵~ 你好呀'
    turns = store.recent_chat_turns('private:2718273234', '2718273234', 10)
    assert [t['role'] for t in turns] == ['user', 'bot']


def test_chat_disabled_or_llm_failure_returns_none(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    event = {'post_type': 'message', 'message_type': 'private', 'user_id': 'u',
             'message': [{'type': 'text', 'data': {'text': 'hi'}}]}
    assert chat.maybe_chat_reply(store, event, make_config(chat_enabled=False)) is None

    def boom(req, timeout=None):
        raise OSError('network down')

    monkeypatch.setattr(chat.netutil, 'open_url', boom)
    assert chat.maybe_chat_reply(store, event, make_config()) is None


def test_chat_group_gating(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return '{"choices": [{"message": {"content": "喵"}}]}'.encode('utf-8')

    monkeypatch.setattr(chat.netutil, 'open_url', lambda req, timeout=None: FakeResp())
    event = {
        'post_type': 'message', 'message_type': 'group', 'group_id': '111', 'user_id': 'u1',
        'message': [{'type': 'text', 'data': {'text': '你好'}}],
    }
    # 限定群：不在列表内不回
    assert chat.maybe_chat_reply(store, event, make_config(chat_groups={'222'})) is None
    # 在列表内回
    assert chat.maybe_chat_reply(store, event, make_config(chat_groups={'111'})) == '喵'
    # 留空 = 全部群
    chat._cooldown.clear()
    assert chat.maybe_chat_reply(store, event, make_config(chat_groups=set())) == '喵'


def test_build_reply_returns_empty_for_unmatched_private_text():
    """私聊普通文本不再被“已收到”兜底拦截，聊天才有机会回复。"""
    from qq_onebot_whitelist.commands import build_reply

    event = {
        'post_type': 'message', 'message_type': 'private', 'user_id': '2718273234',
        'message': [{'type': 'text', 'data': {'text': '你好'}}],
    }
    assert build_reply(event, None) == ''

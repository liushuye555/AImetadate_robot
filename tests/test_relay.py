"""群搬运：范围过滤、普通消息判定、24h 去重、转发调用。"""

import asyncio

from qq_onebot_whitelist import relay
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.config_bridge import config_schema
from qq_onebot_whitelist.store import Store


def make_config(**over):
    base = dict(
        relay_enabled=True,
        relay_mode='whitelist',
        relay_groups={'g1', 'g2'},
        relay_input_groups=set(),
        relay_output_groups=set(),
        relay_ordinary=True,
        relay_text_keywords=[],
        relay_text_regex='',
        relay_ai_filter=False,
        relay_dedupe_hours=24,
    )
    base.update(over)
    return AppConfig(**base)


def test_input_output_filtering():
    cfg = make_config()
    assert relay.relay_input_allows('group:g1', cfg) is True
    assert relay.relay_input_allows('group:g9', cfg) is False
    assert relay.relay_input_allows('private:u', cfg) is False
    assert relay.relay_output_groups('group:g1', cfg) == ['g2']

    explicit = make_config(relay_input_groups={'g5'}, relay_output_groups={'g7'})
    assert relay.relay_input_allows('group:g1', explicit) is False
    assert relay.relay_input_allows('group:g5', explicit) is True
    assert relay.relay_output_groups('group:g5', explicit) == ['g7']

    blacklist = make_config(relay_mode='blacklist', relay_groups={'g1'})
    assert relay.relay_input_allows('group:g2', blacklist) is True
    assert relay.relay_input_allows('group:g1', blacklist) is False


def test_ordinary_worth_relaying():
    cfg = make_config()
    assert relay.ordinary_worth_relaying('看这个', [{'url': 'x'}], [], [], cfg) is True
    assert relay.ordinary_worth_relaying('看这个 https://a.test', [], ['https://a.test'], [], cfg) is True
    assert relay.ordinary_worth_relaying('文件', [], [], ['a.zip'], cfg) is True
    assert relay.ordinary_worth_relaying('随便聊聊', [], [], [], cfg) is False
    assert relay.ordinary_worth_relaying('模型教程', [], [], [], make_config(relay_text_keywords=['教程'])) is True
    assert relay.ordinary_worth_relaying('分享 lora', [], [], [], make_config(relay_text_regex='lora')) is True


def test_relay_dedup_24h(tmp_path):
    store = Store(tmp_path / 'bot.db')
    assert store.relay_seen('abc') is False
    store.relay_log('abc', 'ordinary')
    assert store.relay_seen('abc') is True


def test_relay_event_forwards_and_dedups(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bot.db')
    actions = []

    async def fake_call(ws, action, params):
        actions.append((action, params))
        if action == 'get_forward_msg':
            return {'data': {'messages': [
                {'user_id': 'u9', 'nickname': '小明', 'message': [{'type': 'text', 'data': {'text': '好东西'}}]},
                {'user_id': 'u8', 'nickname': '小红', 'message': [{'type': 'image', 'data': {'url': 'x'}}]},
            ]}}
        return {'status': 'ok'}

    monkeypatch.setattr('qq_onebot_whitelist.onebot.call_action', fake_call)
    cfg = make_config(relay_groups={'111', '222'})
    event = {
        'post_type': 'message', 'message_type': 'group', 'group_id': '111',
        'user_id': 'u1', 'self_id': 'bot',
        'message': [{'type': 'forward', 'data': {'id': 'f1'}}],
    }
    asyncio.run(relay.relay_event(None, store, event, cfg))
    sends = [a for a in actions if a[0] == 'send_forward_msg']
    assert len(sends) == 1
    assert sends[0][1]['group_id'] == 222
    assert len(sends[0][1]['messages']) == 2
    # 再次转发同一内容 → 24h 去重
    actions.clear()
    asyncio.run(relay.relay_event(None, store, event, cfg))
    assert [a for a in actions if a[0] == 'send_forward_msg'] == []


def test_relay_skips_own_messages(tmp_path):
    store = Store(tmp_path / 'bot.db')
    event = {
        'post_type': 'message', 'message_type': 'group', 'group_id': 'g1',
        'user_id': 'bot', 'self_id': 'bot',
        'message': [{'type': 'text', 'data': {'text': 'hi'}}],
    }
    assert asyncio.run(relay.relay_event(None, store, event, make_config())) is None


def test_schema_includes_relay_and_chat():
    keys = [field['key'] for field in config_schema({})]
    assert 'relay.enabled' in keys and 'relay.output_groups' in keys
    assert 'chat.enabled' in keys and 'chat.persona' in keys

import asyncio
import json

from qq_onebot_whitelist import onebot
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.policy import BotConfig
from qq_onebot_whitelist.store import Store


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def group_event(*, user_id="1001", self_id="3001", role="member", text="今晚清理不活跃成员"):
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": "2001",
        "user_id": user_id,
        "self_id": self_id,
        "sender": {"role": role},
        "message": [
            {"type": "at", "data": {"qq": "all"}},
            {"type": "text", "data": {"text": text}},
        ],
    }


def test_handle_event_ignores_self_message_before_side_effects(monkeypatch):
    onebot._group_activity.clear()
    onebot._purge_keepalive_last.clear()
    calls = []
    monkeypatch.setattr(onebot, "record_event", lambda *args: calls.append(args))
    ws = FakeWS()
    event = group_event(user_id="3001", self_id="3001", role="owner")
    config = AppConfig(keepalive_enabled=True, keepalive_message="机器人在线")

    assert asyncio.run(onebot.handle_event(ws, event, config, None)) is False
    assert calls == []
    assert ws.sent == []
    assert onebot._group_activity == {}


def test_echo_same_sender_cannot_trigger():
    onebot._echo_state.clear()
    onebot._echo_last.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=2, echo_window_seconds=60)
    event = group_event(user_id="1001", self_id="3001", text="重复文本")

    assert onebot.echo_reply_text(event, config) is None
    assert onebot.echo_reply_text(event, config) is None


def test_echo_distinct_senders_trigger():
    onebot._echo_state.clear()
    onebot._echo_last.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=2, echo_window_seconds=60)

    assert onebot.echo_reply_text(group_event(user_id="1001", text="重复文本"), config) is None
    assert onebot.echo_reply_text(group_event(user_id="1002", text="重复文本"), config) == "重复文本"


def test_non_admin_purge_announcement_does_not_send_keepalive():
    onebot._purge_keepalive_last.clear()
    ws = FakeWS()
    config = AppConfig(
        keepalive_enabled=True,
        keepalive_message="机器人在线",
        blocked_groups={"2001"},
    )

    assert asyncio.run(onebot.handle_event(ws, group_event(role="member"), config, None)) is False
    assert ws.sent == []


def test_duplicate_admin_purge_announcements_are_cooled_down():
    onebot._purge_keepalive_last.clear()
    ws = FakeWS()
    config = AppConfig(
        keepalive_enabled=True,
        keepalive_message="机器人在线",
        blocked_groups={"2001"},
    )
    event = group_event(role="admin")

    assert asyncio.run(onebot.handle_event(ws, event, config, None)) is False
    assert asyncio.run(onebot.handle_event(ws, event, config, None)) is False
    assert len(ws.sent) == 1


def test_echo_direct_self_message_never_counts():
    onebot._echo_state.clear()
    onebot._echo_last.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=2, echo_window_seconds=60)
    event = group_event(user_id="3001", self_id="3001", text="机器人自己的消息")

    assert onebot.echo_reply_text(event, config) is None
    assert onebot.echo_reply_text(event, config) is None


def test_repair_command_is_rejected_in_group_chat(tmp_path):
    ws = FakeWS()
    store = Store(tmp_path / "bot.db")
    config = AppConfig(data_dir=tmp_path, bot=BotConfig(whitelist_users={"1001"}), language="zh-CN")
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": "2001",
        "user_id": "1001",
        "self_id": "3001",
        "message": [
            {"type": "at", "data": {"qq": "3001"}},
            {"type": "text", "data": {"text": "/修复图片 53619"}},
        ],
    }

    assert asyncio.run(onebot.handle_event(ws, event, config, store)) is True
    assert ws.sent[0]["params"]["message"] == "“修复图片”只能在私聊中使用。"


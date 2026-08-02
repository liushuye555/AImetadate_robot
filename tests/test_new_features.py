from qq_onebot_whitelist import onebot
from qq_onebot_whitelist import control
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.daily_report import build_daily_resource_report


def text_event(group: str, text: str) -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group,
        "user_id": "u1",
        "message": [{"type": "text", "data": {"text": text}}],
    }


def test_echo_triggers_after_min_repeat():
    onebot._echo_state.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=3, echo_window_seconds=60)
    event = text_event("1", "同一句话")
    assert onebot.echo_reply_text(event, config) is None
    assert onebot.echo_reply_text(event, config) is None
    assert onebot.echo_reply_text(event, config) == "同一句话"


def test_echo_respects_group_allowlist():
    onebot._echo_state.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=2, echo_window_seconds=60, echo_groups={"9"})
    assert onebot.echo_reply_text(text_event("1", "x"), config) is None
    assert onebot.echo_reply_text(text_event("1", "x"), config) is None  # 群1不在白名单，永不触发
    assert onebot.echo_reply_text(text_event("9", "x"), config) is None
    assert onebot.echo_reply_text(text_event("9", "x"), config) == "x"


def test_echo_disabled_by_default():
    onebot._echo_state.clear()
    config = AppConfig(echo_enabled=False, echo_min_repeat=1)
    assert onebot.echo_reply_text(text_event("1", "x"), config) is None


def test_collection_allows_defaults_true():
    config = AppConfig()
    assert onebot.collection_allows("123", "images", config) is True
    assert onebot.collection_allows("123", "links", config) is True


def test_collection_allows_respects_profile():
    config = AppConfig(collection_groups={"123": {"images": False, "links": True}})
    assert onebot.collection_allows("123", "images", config) is False
    assert onebot.collection_allows("123", "links", config) is True
    assert onebot.collection_allows("456", "images", config) is True  # 未配置群全量


def test_collection_module_helpers():
    from qq_onebot_whitelist import collection
    assert collection.COLLECTION_KINDS == ("images", "links", "files", "forwards")
    assert collection.is_forward_event({"message_type": "forward"}) is True
    assert collection.is_forward_event({"message": [{"type": "text", "data": {"text": "hi"}}]}) is False


def test_system_cpu_percent_returns_float():
    value = onebot.system_cpu_percent()
    assert isinstance(value, float)
    assert 0.0 <= value <= 100.0


class FakeStore:
    def recent_files(self, **kw):
        return [{"file_name": "a.zip", "scope": "g", "kind": "archive"}]

    def recent_link_records(self, **kw):
        return [{"url": "https://x", "scope": "g", "message_text": ""}]

    def group_name_map(self):
        return {}


def test_daily_report_include_toggles():
    store = FakeStore()
    full = build_daily_resource_report(store, language="zh-CN", enrich_links=False)
    assert "新增链接" in full and "新增文件" in full
    no_links = build_daily_resource_report(store, language="zh-CN", include_links=False, enrich_links=False)
    assert "新增文件" in no_links and "新增链接" not in no_links
    no_files = build_daily_resource_report(store, language="zh-CN", include_files=False, enrich_links=False)
    assert "新增链接" in no_files and "新增文件" not in no_files


def test_cmd_groups_prints_list(capsys, monkeypatch):
    async def fake():
        return [{"id": "123", "name": "测试群"}]

    monkeypatch.setattr(control, "_fetch_groups_once", fake)
    assert control.cmd_groups(None) == 0
    out = capsys.readouterr().out
    assert '"id": "123"' in out and "测试群" in out


def test_load_config_tolerates_empty_max_chunks(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ai_context:\n  max_chunks: ''\n", encoding="utf-8")
    config = load_config(path)
    assert config.ai_context_max_chunks is None

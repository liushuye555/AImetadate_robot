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


def test_collection_pause_marker(monkeypatch, tmp_path):
    from qq_onebot_whitelist import collection
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)
    assert collection.is_collection_paused() is False
    marker.write_text("1", encoding="ascii")
    assert collection.is_collection_paused() is True


def test_collect_event_skips_when_paused(monkeypatch, tmp_path):
    from qq_onebot_whitelist import collection
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)
    marker.write_text("1", encoding="ascii")

    class FakeStore:
        def record_message(self, **kwargs):
            raise AssertionError("暂停时不应采集")

    event = text_event("1", "hi")
    collection.collect_event(FakeStore(), event, AppConfig())  # 不抛异常即通过


def test_cmd_collection_toggles(monkeypatch, tmp_path):
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(control, "PAUSE_MARKER", marker)
    args = type("Args", (), {"state": "off"})()
    assert control.cmd_collection(args) == 0
    assert control.collection_paused() is True
    args.state = "on"
    assert control.cmd_collection(args) == 0
    assert control.collection_paused() is False


def test_match_custom_rules_keywords_and_groups():
    from qq_onebot_whitelist import collection
    config = AppConfig(collection_rules=[
        {"name": "AI会话", "enabled": True, "groups": [], "keywords": ["lora", "checkpoint"], "regex": ""},
        {"name": "教程", "enabled": True, "groups": ["9"], "keywords": ["教程"], "regex": ""},
        {"name": "正则规则", "enabled": True, "groups": [], "keywords": [], "regex": r"编号[:：]?(\d+)"},
        {"name": "禁用", "enabled": False, "groups": [], "keywords": ["x"], "regex": ""},
    ])
    event = text_event("1", "这个 lora 不错")
    matched = collection.match_custom_rules(event, "这个 lora 不错", config)
    names = [r["name"] for r in matched]
    assert "AI会话" in names
    assert "教程" not in names          # 群不在范围内
    assert "禁用" not in names

    matched_regex = collection.match_custom_rules(text_event("1", "文件编号:12345"), "文件编号:12345", config)
    assert "正则规则" in [r["name"] for r in matched_regex]


def test_collect_custom_records_matched(tmp_path, monkeypatch):
    from qq_onebot_whitelist import collection
    from qq_onebot_whitelist.store import Store
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)
    store = Store(tmp_path / "bot.db")
    config = AppConfig(collection_rules=[
        {"name": "AI会话", "enabled": True, "groups": [], "keywords": ["lora"], "regex": "",
         "collect_images": True, "collect_links": True, "collect_files": True},
    ])
    event = text_event("1", "分享一个 lora 模型")
    collection.collect_custom(store, event, "分享一个 lora 模型", config)
    rows = store.recent_custom_collections(rule="AI会话")
    assert len(rows) == 1
    assert "lora" in rows[0]["text"]
    assert rows[0]["rule"] == "AI会话"


def test_cmd_custom_prints_records(tmp_path, monkeypatch, capsys):
    from qq_onebot_whitelist import collection
    from qq_onebot_whitelist.store import Store
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)
    store = Store(tmp_path / "bot.db")
    store.record_custom_collection(rule="AI会话", scope="1", user_id="u", text="test lora")
    monkeypatch.setattr(control, "load_stats", lambda: None)  # 不相关，占位
    monkeypatch.setattr("qq_onebot_whitelist.config.load_config", lambda path: AppConfig(data_dir=tmp_path))
    args = type("Args", (), {"rule": None})()
    assert control.cmd_custom(args) == 0
    out = capsys.readouterr().out
    assert "AI会话" in out and "test lora" in out

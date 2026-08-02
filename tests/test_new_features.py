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


def test_echo_interleaved_text_resets():
    onebot._echo_state.clear()
    onebot._echo_last.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=2, echo_window_seconds=0)
    assert onebot.echo_reply_text(text_event("1", "aaa"), config) is None
    assert onebot.echo_reply_text(text_event("1", "bbb"), config) is None
    assert onebot.echo_reply_text(text_event("1", "aaa"), config) is None  # 被 bbb 打断，不连续
    assert onebot.echo_reply_text(text_event("1", "aaa"), config) == "aaa"  # 连续两条 aaa 触发


def test_echo_unlimited_window_consecutive():
    onebot._echo_state.clear()
    onebot._echo_last.clear()
    config = AppConfig(echo_enabled=True, echo_min_repeat=3, echo_window_seconds=0)
    assert onebot.echo_reply_text(text_event("1", "x"), config) is None
    assert onebot.echo_reply_text(text_event("1", "x"), config) is None
    assert onebot.echo_reply_text(text_event("1", "x"), config) == "x"


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


def test_forward_ids_extraction():
    from qq_onebot_whitelist import collection
    event = {"message": [{"type": "forward", "data": {"id": "abc"}}, {"type": "text", "data": {"text": "x"}}]}
    assert collection.forward_ids(event) == ["abc"]


def test_ai_match_message_parses_answer(monkeypatch):
    from qq_onebot_whitelist import collection
    import json as json_mod

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json_mod.dumps({"choices": [{"message": {"content": "是"}}]}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResp())
    llm = type("C", (), {"model": "m", "base_url": "https://x", "api_key": "k", "timeout_seconds": 10})()
    assert collection.ai_match_message("abc", "收集 abc", llm) is True


def test_ai_match_and_collect_records(tmp_path, monkeypatch):
    from qq_onebot_whitelist import collection
    from qq_onebot_whitelist.store import Store
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)
    llm = type("C", (), {"model": "m", "base_url": "https://x", "api_key": "k", "timeout_seconds": 10})
    monkeypatch.setattr(collection, "_llm_config", lambda: llm())
    monkeypatch.setattr(collection, "ai_match_message",
                        lambda text, prompt, cfg: "midjourney" in prompt.lower())
    store = Store(tmp_path / "bot.db")
    config = AppConfig(collection_rules=[
        {"name": "AI收集", "enabled": True, "groups": [], "ai_match": True, "ai_prompt": "Midjourney 技巧"}
    ])
    event = text_event("1", "分享个技巧")
    collection.ai_match_and_collect(store, event, "分享个技巧", config)
    rows = store.recent_custom_collections(rule="AI收集")
    assert len(rows) == 1


def test_config_parses_expand_forwards(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("collection:\n  expand_forwards: true\n", encoding="utf-8")
    config = load_config(path)
    assert config.collection_expand_forwards is True


def test_keepalive_targets_modes(monkeypatch):
    import asyncio
    from qq_onebot_whitelist import onebot

    async def fake_fetch(ws, config):
        return {"1", "2", "3"}

    monkeypatch.setattr(onebot, "_fetch_group_ids", fake_fetch)
    config_all = AppConfig(keepalive_mode="all", blocked_groups={"3"})
    assert asyncio.run(onebot.keepalive_targets(None, config_all)) == {"1", "2"}

    config_white = AppConfig(keepalive_mode="whitelist")
    config_white.bot.whitelist_groups = {"9"}
    assert asyncio.run(onebot.keepalive_targets(None, config_white)) == {"9"}

    config_custom = AppConfig(keepalive_mode="custom", keepalive_groups={"7"})
    assert asyncio.run(onebot.keepalive_targets(None, config_custom)) == {"7"}


def test_config_keepalive_new_fields(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "keepalive:\n  mode: whitelist\n  trigger_enabled: true\n  idle_minutes: 30\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.keepalive_mode == "whitelist"
    assert config.keepalive_trigger_enabled is True
    assert config.keepalive_idle_minutes == 30


def test_contains_at_all_detection():
    from qq_onebot_whitelist import onebot
    assert onebot.contains_at_all({"message": [{"type": "at", "data": {"qq": "all"}}]}) is True
    assert onebot.contains_at_all({"message": [{"type": "text", "data": {"text": "@全体成员 清理"}}]}) is True
    assert onebot.contains_at_all({"message": [{"type": "text", "data": {"text": "普通消息"}}]}) is False


def test_purge_announcement_requires_keywords():
    from qq_onebot_whitelist import onebot
    purge = {"message": [{"type": "at", "data": {"qq": "all"}}, {"type": "text", "data": {"text": "今晚清理死人"}}]}
    assert onebot.is_purge_announcement(purge) is True
    notice = {"message": [{"type": "at", "data": {"qq": "all"}}, {"type": "text", "data": {"text": "今晚八点活动"}}]}
    assert onebot.is_purge_announcement(notice) is False
    plain_at_all = {"message": [{"type": "at", "data": {"qq": "all"}}]}
    assert onebot.is_purge_announcement(plain_at_all) is False


def test_is_sticker_format():
    from qq_onebot_whitelist.images import is_sticker_format
    assert is_sticker_format({"format": "GIF", "size": 1000, "width": 100, "height": 100}) is True
    assert is_sticker_format({"format": "PNG", "size": 5000, "width": 200, "height": 200}) is True
    assert is_sticker_format({"format": "PNG", "size": 5000000, "width": 2000, "height": 2000}) is False
    assert is_sticker_format({"format": "PNG", "size": 1000, "width": 100, "height": 100, "has_ai_metadata": True}) is False


def test_sticker_requires_repeat_count(tmp_path, monkeypatch):
    from qq_onebot_whitelist import collection
    from qq_onebot_whitelist.store import Store
    marker = tmp_path / "collection-paused"
    monkeypatch.setattr(collection, "PAUSE_MARKER", marker)

    def fake_extract(event):
        return [{"url": "http://x/1.png", "file": "1.png"}]

    def fake_process(url, **kw):
        return {
            "sha256": "abc", "format": "GIF", "size": 1000, "width": 100, "height": 100,
            "retention_reason": "candidate", "kept_path": None,
        }

    monkeypatch.setattr(collection, "extract_image_segments", fake_extract)
    monkeypatch.setattr(collection, "process_image_url", fake_process)
    store = Store(tmp_path / "bot.db")
    config = AppConfig(sticker_repeat_threshold=3)
    event = text_event("1", "图")
    collection.collect_event(store, event, config)  # 第 1 次：未达阈值
    rows = store.recent_images_all(limit=5)
    assert rows and rows[0].get("retention_reason") != "sticker_filtered"
    for _ in range(2):  # 再插入 2 次，累计 3 次达到阈值
        store.record_image(scope="group:1", user_id="u", result={
            "sha256": "abc", "format": "GIF", "size": 1000, "width": 100, "height": 100,
            "kept_path": None, "retention_reason": "candidate",
        }, raw={})
    collection.collect_event(store, event, config)  # 第 4 次：达阈值 → 表情包
    rows = store.recent_images_all(limit=5)
    assert rows[0].get("retention_reason") == "sticker_filtered"

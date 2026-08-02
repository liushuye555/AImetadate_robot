from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.daily_report import build_daily_resource_report
from qq_onebot_whitelist.onebot import record_event
from qq_onebot_whitelist.store import Store


def test_feature_flags_default_to_enabled_for_legacy_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.feature_link_analysis is True
    assert config.feature_link_metadata is True
    assert config.feature_image_processing is True
    assert config.feature_ai_context is True
    assert config.feature_daily_report is True
    assert config.feature_startup_history is True
    assert config.feature_auto_restart is True
    assert config.keepalive_enabled is False
    assert config.keepalive_interval_minutes == 0


def test_feature_flags_can_disable_individual_features(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "features:\n"
        "  link_analysis: false\n"
        "  link_metadata: false\n"
        "  image_processing: false\n"
        "  ai_context: false\n"
        "  daily_report: false\n"
        "  startup_history: false\n"
        "  auto_restart: false\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.feature_link_analysis is False
    assert config.feature_link_metadata is False
    assert config.feature_image_processing is False
    assert config.feature_ai_context is False
    assert config.feature_daily_report is False
    assert config.feature_startup_history is False
    assert config.feature_auto_restart is False


def test_disabling_link_analysis_keeps_urls_without_classifying_them(tmp_path):
    store = Store(tmp_path / "bot.db")
    store.record_link(
        scope="group:1",
        user_id="u",
        url="https://github.com/a/b",
        message_text="模型工作流",
    )

    report = build_daily_resource_report(store, analyze_links=False)

    assert "https://github.com/a/b" in report
    assert "核心AI资源" not in report


def test_disabling_image_processing_still_records_message(tmp_path):
    store = Store(tmp_path / "bot.db")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("features:\n  image_processing: false\n", encoding="utf-8")
    config = load_config(config_path)
    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 1,
        "message": [{"type": "text", "data": {"text": "hello"}}],
    }

    record_event(store, event, config)

    assert store.recent_records_all(limit=1)[0]["text"] == "hello"

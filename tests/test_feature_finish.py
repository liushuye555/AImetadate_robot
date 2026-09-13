from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.resource_view import select_resource_links, write_resource_pages
from qq_onebot_whitelist.resources import link_category
from qq_onebot_whitelist.store import Store


def test_link_metadata_keeps_resolved_url(tmp_path):
    from qq_onebot_whitelist.link_metadata import get_or_fetch_link_metadata

    store = Store(tmp_path / "bot.db")
    result = get_or_fetch_link_metadata(
        store,
        "https://b23.tv/abc",
        fetcher=lambda url: {
            "title": "教程",
            "description": "视频说明",
            "resolved_url": "https://www.bilibili.com/video/BV1xx",
        },
    )

    assert result["resolved_url"] == "https://www.bilibili.com/video/BV1xx"
    assert store.get_link_metadata("https://b23.tv/abc")["resolved_url"] == "https://www.bilibili.com/video/BV1xx"


def test_link_category_keeps_cloud_drive_separate_from_ai_model():
    assert link_category("https://pan.baidu.com/s/abc", "模型下载") == "网盘资源"


def test_resource_selection_uses_resolved_url_and_skips_direct_image_links(tmp_path):
    store = Store(tmp_path / "bot.db")
    store.record_link(
        scope="group:1",
        user_id="u",
        url="https://b23.tv/abc",
        message_text="教程视频",
    )
    store.save_link_metadata(
        "https://b23.tv/abc",
        "B站教程",
        "教学视频",
        resolved_url="https://www.bilibili.com/video/BV1xx",
    )
    store.record_link(
        scope="group:1",
        user_id="u",
        url="https://i.imgur.com/example.png",
        message_text="模型下载",
    )

    links = select_resource_links(store, mode="rule")

    assert len(links) == 1
    assert links[0]["category"] == "AI教程视频"
    assert links[0]["url"] == "https://www.bilibili.com/video/BV1xx"


def test_resource_page_has_safe_external_link_and_copy_button(tmp_path):
    store = Store(tmp_path / "bot.db")
    store.record_link(
        scope="group:1",
        user_id="u",
        url="https://example.com/a?token=secret",
        message_text="一个小网站",
    )

    write_resource_pages(tmp_path / "view", store)
    html = (tmp_path / "view" / "resources.html").read_text(encoding="utf-8")

    assert "复制链接" in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_repair_command_parser_accepts_id_or_scan():
    from qq_onebot_whitelist.commands import parse_repair_images_command

    assert parse_repair_images_command("/修复图片 53619") == 53619
    assert parse_repair_images_command("修复图片") is None
    assert parse_repair_images_command("收藏夹") is False


def test_saved_view_uses_real_png_fixture(tmp_path):
    """The production verifier must keep rejecting fake bytes; saved view uses valid media."""
    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    image = data / "images" / "ai" / "aa" / ("b" * 64 + ".png")
    image.parent.mkdir(parents=True)
    Image.new("RGB", (10, 20), color=(20, 40, 60)).save(image, format="PNG")
    store.record_image(
        scope="private:u1",
        user_id="u1",
        result={
            "url": "https://img.test/a.png",
            "sha256": "b" * 64,
            "size": image.stat().st_size,
            "format": "PNG",
            "width": 10,
            "height": 20,
            "kept_path": str(image),
            "retention_reason": "chat_record_saved",
            "saved_category": "未分类",
        },
        raw={"forward_id": "f1"},
    )

    counts = build_view(tmp_path)
    assert counts["06_聊天记录收藏/未分类"] == 1
    assert (data / "view" / "06_聊天记录收藏" / "未分类" / "index.html").exists()

import pytest

from qq_onebot_whitelist.knowledge_view import render_views


@pytest.mark.parametrize(
    "filename",
    ["knowledge.html", "glossary.html", "knowledge-summary.html", "knowledge-files.html"],
)
def test_empty_report_explains_publishing_and_auto_analysis(tmp_path, monkeypatch, filename):
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_view.render_evidence", lambda *_: "")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_token", lambda *_: "token")
    monkeypatch.setattr("qq_onebot_whitelist.knowledge_feedback.feedback_script", lambda _: "")

    page = render_views(tmp_path, items=[], runs=[], assets=[], glossary=[])[filename]

    assert "本页暂无正式资料。" in page
    assert "若已完成历史分析，请先发布整理结果。" in page
    assert "如需持续整理" in page
    assert "采集 → 群知识" in page
    assert "查看已有资料无需启用自动分析。" in page
    assert "开启需要的整理功能" not in page

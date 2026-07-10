from qq_onebot_whitelist.html_render import render_markdown


def test_render_markdown_supports_common_summary_format_and_escapes_html():
    rendered = render_markdown('## 概览\n\n- **重点**：`模型`\n\n<script>alert(1)</script>')

    assert '<h2>概览</h2>' in rendered
    assert '<strong>重点</strong>' in rendered
    assert '<code>模型</code>' in rendered
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered

"""Render separated, local-only knowledge report pages."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .content_utils import redact_secrets
from .knowledge_evidence import render_evidence


PAGES = (
    ("knowledge.html", "知识", "knowledge.html"),
    ("glossary.html", "术语", "glossary.html"),
    ("knowledge-summary.html", "总结", "knowledge-summary.html"),
    ("knowledge-files.html", "文件", "knowledge-files.html"),
)


def _safe(value) -> str:
    return escape(redact_secrets(str(value if value is not None else "")), quote=True)


def _ids(row: dict) -> list[int]:
    value = row.get("evidence_ids", row.get("evidence_json", []))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = []
    return [item for item in value if type(item) is int and item > 0] if isinstance(value, list) else []


def _nav(current: str) -> str:
    links = []
    for filename, label, href in PAGES:
        active = filename == current
        links.append(f'<a href="{href}"' + (' aria-current="page"' if active else '') + f'>{label}</a>')
    return '<nav aria-label="报告分类">' + " · ".join(links) + '</nav>'


def _frame(filename: str, title: str, cards: list[str], groups: set[str], filters: str) -> str:
    opts = ''.join(f'<option value="{_safe(group)}">{_safe(group)}</option>' for group in sorted(groups))
    count = len(cards)
    content = ''.join(cards) if cards else '<p class="empty">暂无内容。</p>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
body{{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;background:#f4f6f8;color:#202633;max-width:980px;margin:28px auto;padding:0 18px}}nav{{padding:12px 16px;background:#e8edf4;border-radius:10px}}nav a{{color:#174e87;text-decoration:none;padding:4px 8px}}nav a[aria-current]{{font-weight:700;color:#172b46;text-decoration:underline}}.filters{{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}}input,select{{font:inherit;padding:8px 10px;border:1px solid #aab4c2;border-radius:7px;background:white}}article{{background:white;padding:18px 20px;margin:14px 0;border-radius:10px;box-shadow:0 1px 4px #172b4612}}article h2{{font-size:1.2rem;margin:.1rem 0 .4rem}}p.meta{{color:#586174;font-size:.92rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}details{{margin-top:10px}}.empty{{padding:24px;background:white;border-radius:10px}}footer{{color:#657184;font-size:.9rem;margin:28px 0}}
</style></head><body><header><h1>{title}</h1><p>共 {count} 项。来源编号为本地消息数据库编号。</p>{_nav(filename)}</header>
<div class="filters"><label>群组 <select id="group"><option value="">全部群</option>{opts}</select></label>{filters}<label>搜索 <input id="search" type="search" placeholder="搜索本页内容" aria-label="搜索本页内容"></label></div>
<main>{content}</main><p id="filter-empty" hidden>没有符合筛选条件的内容。</p><footer>内容来自本地群消息记录与分析结果；引用编号仅在本机数据库中有效。</footer>
<script>const group=document.getElementById('group'),search=document.getElementById('search');function filterRows(){{const g=group.value,q=search.value.toLocaleLowerCase(),v=document.getElementById('value')?.value||'',s=document.getElementById('term-status')?.value||'';let count=0;document.querySelectorAll('article').forEach(card=>{{card.hidden=!!((g&&card.dataset.group!==g)||!card.textContent.toLocaleLowerCase().includes(q)||(v&&card.dataset.value!==v)||(s&&card.dataset.status!==s&&card.dataset.origin!==s));if(!card.hidden)count++;}});document.getElementById('filter-empty').hidden=count>0;}}group.addEventListener('change',filterRows);search.addEventListener('input',filterRows);document.getElementById('value')?.addEventListener('change',filterRows);document.getElementById('term-status')?.addEventListener('change',filterRows);</script>
</body></html>'''


def render_views(data_dir: Path, *, items: list[dict], runs: list[dict], assets: list[dict],
                 glossary: list[dict]) -> dict[str, str]:
    """Return four independent static pages for knowledge, terms, summaries, and files."""
    data_dir = Path(data_dir)
    groups = {str(row.get("scope") or "") for rows in (items, runs, assets, glossary)
              for row in rows if row.get("scope")}

    def evidence(scope, ids):
        return render_evidence(data_dir, str(scope or ""), ids)

    knowledge_cards = []
    for item in items:
        ids = _ids(item)
        val = "high" if item.get("value") == "high" else "candidate"
        state = {"unresolved": "未解决", "reported": "群友说法", "verified": "原消息有验证反馈",
                 "disputed": "存在分歧"}.get(item.get("evidence_state"), "群友说法")
        msgrefs = "、".join("#" + str(mid) for mid in ids) or "无来源编号"
        knowledge_cards.append(
            f'<article data-group="{_safe(item.get("scope"))}" data-value="{val}">'
            f'<h2>{_safe(item.get("title"))}</h2><p class="meta">{_safe(item.get("scope"))} · {_safe(item.get("created_at"))} · '
            f'{_safe(item.get("topic"))} · {_safe(item.get("kind"))} · '
            f'{"精选" if val == "high" else "待确认"} · {state} · {msgrefs}</p>'
            f'<pre>{_safe(item.get("body", item.get("summary")))}</pre>{evidence(item.get("scope"), ids)}'
            f'{_feedback_controls(item)}</article>')
    knowledge_filters = '<label>价值 <select id="value"><option value="">全部知识</option><option value="high">精选讨论</option><option value="candidate">待确认讨论</option></select></label>'
    knowledge_html = _frame("knowledge.html", "群知识", knowledge_cards, groups, knowledge_filters)
    knowledge_html = knowledge_html.replace('<h1>群知识</h1>', '<h1>群知识</h1><p>文字讨论可独立收录，不要求图片或附件。术语解释可从术语页独立查看。</p>')
    from .knowledge_feedback import feedback_script, feedback_token
    knowledge_html = knowledge_html.replace("</body>", feedback_script(feedback_token(data_dir)) + "</body>")

    term_cards = []
    for term in glossary:
        origin = term.get("origin") or "ai"
        status = term.get("status") or "candidate"
        label = "人工解释" if origin == "user" else ("已用于本群分析" if status == "active" else "候选解释")
        meaning = term.get("meaning") or ""
        # Effective terms are prepared by the caller; preserve the human wording for user-origin entries.
        explanation = meaning
        ids = _ids(term)
        reftext = "、".join("#" + str(mid) for mid in ids) or "无来源编号"
        term_cards.append(f'<article data-group="{_safe(term.get("scope"))}" data-status="{_safe(status)}" data-origin="{_safe(origin)}">'
                          f'<h2>{_safe(term.get("term"))}</h2><p class="meta">{_safe(term.get("scope"))} · {label} · {reftext}</p>'
                          f'<pre>{_safe(explanation)}</pre>{evidence(term.get("scope"), ids)}</article>')
    term_filters = '<label>解释状态 <select id="term-status"><option value="">全部</option><option value="candidate">候选</option><option value="active">已用于本群分析</option><option value="user">人工解释</option></select></label>'
    glossary_html = _frame("glossary.html", "群内术语", term_cards, groups, term_filters)

    summary_cards = []
    for run in runs:
        result = run.get("result")
        if result is None:
            try:
                result = json.loads(run.get("result_json") or "{}")
            except (ValueError, TypeError):
                result = {}
        if not isinstance(result, dict):
            continue
        summaries = result.get("summary") or []
        if isinstance(summaries, str):
            summaries = [{"text": summaries, "evidence_ids": []}]
        if not summaries:
            continue
        text_parts, ids = [], []
        for row in summaries:
            if not isinstance(row, dict):
                continue
            refids = _ids(row)
            ids.extend(refids)
            text_parts.append(_safe(row.get("text")) + (" [" + "、".join("#" + str(i) for i in refids) + "]" if refids else ""))
        coverage = result.get("input_count", run.get("input_count", 0))
        summary_text = '\n'.join(text_parts)
        summary_cards.append(f'<article data-group="{_safe(run.get("scope"))}"><h2>群总结 · {_safe(run.get("scope"))}</h2>'
                             f'<p class="meta">{_safe(run.get("created_at"))} · {_safe(run.get("kind"))} · 覆盖 {_safe(coverage)} 条消息</p>'
                             f'<pre>{summary_text}</pre>{evidence(run.get("scope"), sorted(set(ids)))}</article>')
    summary_html = _frame("knowledge-summary.html", "群聊总结", summary_cards, groups, "")

    file_cards = []
    for asset in assets:
        ids = [asset.get("message_id")] if type(asset.get("message_id")) is int and asset.get("message_id") > 0 else []
        file_cards.append(f'<article data-group="{_safe(asset.get("scope"))}"><h2>文件 · {_safe(asset.get("name"))}</h2>'
                          f'<p class="meta">{_safe(asset.get("scope"))} · {_safe(asset.get("status"))} · 原消息 '
                          f'{("#" + str(ids[0])) if ids else "编号不可用"}</p><pre>{_safe(asset.get("path") or asset.get("error") or "未保存本体")}</pre>'
                          f'{evidence(asset.get("scope"), ids)}</article>')
    files_html = _frame("knowledge-files.html", "群文件", file_cards, groups, "")
    return {"knowledge.html": knowledge_html, "glossary.html": glossary_html,
            "knowledge-summary.html": summary_html, "knowledge-files.html": files_html}


def _feedback_controls(item: dict) -> str:
    from .knowledge_feedback import feedback_controls
    key = item.get("key") or item.get("item_key") or ""
    return feedback_controls(str(item.get("scope") or ""), str(key)) if key else ""

"""Render separated, local-only knowledge report pages."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from .content_utils import redact_secrets
from .knowledge_evidence import render_evidence
from .knowledge_layers import CATEGORIES, category_for
from .knowledge_lifecycle import lifecycle_for
from .knowledge_organization import TOPICS


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
<p>当前显示 <span id="shown-count">{count}</span> 项</p><main>{content}</main><p id="filter-empty" hidden>没有符合筛选条件的内容。</p><footer>内容来自本地群消息记录与分析结果；引用编号仅在本机数据库中有效。</footer>
<script>const group=document.getElementById('group'),search=document.getElementById('search');function filterRows(){{const g=group.value,q=search.value.toLocaleLowerCase(),v=document.getElementById('value')?.value||'',s=document.getElementById('term-status')?.value||'',c=document.getElementById('category')?.value||'',k=document.getElementById('term-kind')?.value||'',lane=document.getElementById('lane')?.value||'',topic=document.getElementById('topic')?.value||'';let count=0;document.querySelectorAll('article').forEach(card=>{{const category=card.dataset.category||'knowledge',topics=(card.dataset.topics||'').split(','),base=!(g&&card.dataset.group!==g)&&!(v&&card.dataset.value!==v)&&!(c==='durable'&&category==='transient')&&!(c&&c!=='durable'&&category!==c)&&!(lane&&card.dataset.lane!==lane)&&!(topic&&!topics.includes(topic)),variants=card.querySelectorAll?.('[data-term-variant]')||[];if(variants.length){{let any=false;const shared=(card.dataset.termShared||'').toLocaleLowerCase();variants.forEach(item=>{{const matchesSearch=!q||shared.includes(q)||(item.textContent||'').toLocaleLowerCase().includes(q);item.hidden=!(base&&matchesSearch&&(!s||(item.dataset.status===s||item.dataset.origin===s))&&(!k||item.dataset.inference===k));if(!item.hidden)any=true;}});card.hidden=!any;}}else{{card.hidden=!(base&&card.textContent.toLocaleLowerCase().includes(q)&&(!s||(card.dataset.status===s||card.dataset.origin===s))&&(!k||card.dataset.inference===k));}}if(!card.hidden)count++;}});document.getElementById('filter-empty').hidden=count>0;const shown=document.getElementById('shown-count');if(shown)shown.textContent=count;}}group.addEventListener('change',filterRows);search.addEventListener('input',filterRows);document.getElementById('value')?.addEventListener('change',filterRows);document.getElementById('term-status')?.addEventListener('change',filterRows);document.getElementById('category')?.addEventListener('change',filterRows);document.getElementById('term-kind')?.addEventListener('change',filterRows);document.getElementById('lane')?.addEventListener('change',filterRows);document.getElementById('topic')?.addEventListener('change',filterRows);filterRows();</script>
</body></html>'''


def render_views(data_dir: Path, *, items: list[dict], runs: list[dict], assets: list[dict],
                 glossary: list[dict], threads: list[dict] | None = None,
                 profiles: dict | None = None, manual_archives: dict | None = None,
                 now=None) -> dict[str, str]:
    """Return four independent static pages for knowledge, terms, summaries, and files."""
    data_dir = Path(data_dir)
    groups = {str(row.get("scope") or "") for rows in (items, runs, assets, glossary)
              for row in rows if row.get("scope")}

    def evidence(scope, ids):
        return render_evidence(data_dir, str(scope or ""), ids)

    threads = threads or []
    tracked_keys = {event['item_key'] for thread in threads for event in thread.get('events', [])}
    profiles = profiles or {}
    manual_archives = manual_archives or {}

    def life(row, record_type):
        scope = str(row.get('scope') or '')
        record_id = row.get('id') if record_type == 'topic' else row.get('key')
        return lifecycle_for(row, profile=profiles.get(scope),
                             manual=manual_archives.get((scope, record_type, record_id)), now=now)

    knowledge_cards = []
    for item in items:
        if item.get('key') in tracked_keys:
            continue
        ids = _ids(item)
        category = category_for(item)
        item_row = {**item, 'category': category}
        lifecycle = life(item_row, 'item')
        organization = item.get('organization') if isinstance(item.get('organization'), dict) else {}
        topic_ids = [value for value in organization.get('topics', []) if isinstance(value, str)] or ['other']
        val = "high" if item.get("value") == "high" else "candidate"
        state = {"unresolved": "未解决", "reported": "群友说法", "verified": "原消息有验证反馈",
                 "disputed": "存在分歧"}.get(item.get("evidence_state"), "群友说法")
        msgrefs = "、".join("#" + str(mid) for mid in ids) or "无来源编号"
        knowledge_cards.append(
            f'<article data-group="{_safe(item.get("scope"))}" data-value="{val}" data-category="{category}" data-lane="{lifecycle["lane"]}" data-topics="{_safe(",".join(topic_ids))}">'
            f'<h2>{_safe(item.get("title"))}</h2><p class="meta">主题：{_safe("、".join(TOPICS.get(t,t) for t in topic_ids))}</p><p class="meta">{_safe(item.get("scope"))} · {_safe(item.get("created_at"))} · '
            f'{_safe(item.get("topic"))} · {_safe(item.get("kind"))} · '
            f'{CATEGORIES[category]} · {"精选" if val == "high" else "待确认"} · {state} · {msgrefs}</p>'
            f'<pre>{_safe(item.get("body", item.get("summary")))}</pre>{_details({**item, "lifecycle": lifecycle})}{evidence(item.get("scope"), ids)}'
            f'{_feedback_controls(item)}</article>')
    by_key = {item.get('key'): item for item in items}
    for thread in threads:
        groups.add(thread['scope'])
        events = []
        for original in thread.get('events', []):
            event = dict(original)
            linked_item = by_key.get(event.get('item_key'), {})
            if not isinstance(event.get('organization'), dict) and isinstance(linked_item.get('organization'), dict):
                event['organization'] = linked_item['organization']
            events.append(event)
        latest = by_key.get(events[-1]['item_key'], {}) if events else {}
        category = category_for(thread)
        topic_ids = sorted({topic for event in events
                            for topic in ((event.get('organization') or {}).get('topics', [])
                                          if isinstance(event.get('organization'), dict) else [])
                            if isinstance(topic, str)})
        topic_ids = topic_ids or ['other']
        lifecycle_category = (events[-1].get('category') or None) if events else thread.get('category')
        lifecycle = life({**thread, 'events': events, 'category': lifecycle_category}, 'topic')
        category = lifecycle.get('category') if lifecycle.get('category') in CATEGORIES else category
        val = 'high' if thread.get('value') == 'high' else 'candidate'
        current_state = events[-1].get('evidence_state', 'reported') if events else 'reported'
        state_label = {'unresolved': '未解决', 'reported': '群友说法',
                       'verified': '原消息有验证反馈', 'disputed': '存在分歧'}.get(current_state, '群友说法')
        timeline = []
        for event in events:
            event_org = event.get('organization') if isinstance(event.get('organization'), dict) else {}
            subject = event_org.get('subject') if isinstance(event_org.get('subject'), dict) else {}
            subject_note = '<p class="meta">对象指代待确认</p>' if subject.get('ambiguous') else ''
            timeline.append('<section><p>' + _time(event.get('source_time')) + ' · '
                            + _status(event['status'], event.get('category')) + '</p><pre>' + _safe(event.get('summary')) + '</pre>'
                            + subject_note
                            + ('<p>关联依据：' + _safe(event['link_reason']) + '</p>' if event.get('link_reason') else '')
                            + ('<p>缺少本批验证反馈，解决状态未采纳。</p>' if event.get('status_reason') else '')
                            + evidence(thread['scope'], event['evidence_ids'])
                            + _feedback_controls(by_key.get(event['item_key'], {})) + '</section>')
        knowledge_cards.append(f'<article data-group="{_safe(thread["scope"])}" data-value="{val}" data-category="{category}" data-lane="{lifecycle["lane"]}" data-topics="{_safe(",".join(topic_ids))}">'
            f'<h2>{_safe(thread["title"])}</h2><p class="meta">主题：{_safe("、".join(TOPICS.get(t,t) for t in topic_ids))}</p><p class="meta">{CATEGORIES[category]} · {"精选" if val == "high" else "待确认"} · {state_label} · {_status(thread["status"], category)} · 话题记录 {len(events)} 次</p>'
            + _details({'known': thread.get('known'), 'missing': thread.get('missing'), 'source_time': thread.get('source_time'),
                        'resource': thread.get('resource'), 'quality': latest.get('quality'),
                        'quality_reason': latest.get('quality_reason'), 'lifecycle': lifecycle})
            + '<details><summary>查看讨论进展与证据</summary>' + ''.join(timeline) + '</details></article>')
    knowledge_filters = '<label>处理队列 <select id="lane"><option value="knowledge">知识</option><option value="followup">待跟进</option><option value="archive">归档</option><option value="">全部</option></select></label>'
    knowledge_filters += '<label>主题 <select id="topic"><option value="">全部主题</option>' + ''.join(
        f'<option value="{_safe(key)}">{_safe(label)}</option>' for key, label in TOPICS.items()) + '</select></label>'
    knowledge_filters += '<label>资料类型 <select id="category"><option value="">全部类型</option>' + ''.join(
        f'<option value="{key}">{label}</option>' for key, label in CATEGORIES.items()) + '</select></label>'
    knowledge_filters += '<label>价值 <select id="value"><option value="">全部知识</option><option value="high">精选讨论</option><option value="candidate">待确认讨论</option></select></label>'
    knowledge_html = _frame("knowledge.html", "群知识", knowledge_cards, groups, knowledge_filters)
    knowledge_html = knowledge_html.replace('<h1>群知识</h1>', '<h1>群知识</h1><p>文字讨论可独立收录，不要求图片或附件。术语解释可从术语页独立查看。</p>')
    from .knowledge_feedback import feedback_script, feedback_token
    knowledge_html = knowledge_html.replace("</body>", feedback_script(feedback_token(data_dir)) + "</body>")

    from .knowledge_glossary_groups import group_glossary
    term_cards = []
    for group in group_glossary(glossary):
        term = group["variants"][0]
        term_scope = group["scope"]
        variant_cards = []
        spelling_count = len(group["spellings"])
        for term in group["variants"]:
            origin = term.get("origin") or "ai"
            status = term.get("status") or "candidate"
            label = "人工解释" if origin == "user" else ("已用于本群分析" if status == "active" else "候选解释")
            meaning = term.get("meaning") or ""
            explanation = meaning
            ids = _ids(term)
            reftext = "、".join("#" + str(mid) for mid in ids) or "无来源编号"
            inferred = {'explicit': '原文明确解释', 'inferred': '上下文推断', 'ambiguous': '含义有分歧',
                        'unconfirmed': '解释待确认'}.get(term.get('inference_kind'), '解释待确认')
            annotation = ('<p>解释依据：' + inferred + '</p><pre>' + _safe(term.get('inference_note') or '') + '</pre>')
            if term.get('aliases'):
                annotation += '<p>原文别名：' + _safe('、'.join(term['aliases'])) + '</p>'
            if term.get('alternatives'):
                annotation += '<p>不同解释：</p><ul>' + ''.join('<li>' + _safe(text) + '</li>' for text in term['alternatives']) + '</ul>'
            for field, caption in (("definition_evidence", "释义原文"), ("inference_evidence", "推断用例")):
                quotes = term.get(field) if isinstance(term.get(field), list) else []
                if quotes:
                    annotation += '<p>' + caption + '：</p><ul>' + ''.join(
                        '<li>#' + _safe(item.get('message_id')) + '：' + _safe(item.get('quote')) + '</li>'
                        for item in quotes if isinstance(item, dict) and item.get('quote')) + '</ul>'
            variant_cards.append(f'<section data-term-variant="1" data-status="{_safe(status)}" data-origin="{_safe(origin)}" data-inference="{_safe(term.get("inference_kind") or "unconfirmed")}">'
                                  f'<h3>{_safe(explanation)}</h3><p class="meta">{label} · {reftext}</p>{annotation}{evidence(term_scope, ids)}</section>')
        spellings = '、'.join(_safe(value) for value in group["spellings"])
        term_cards.append(f'<article data-group="{_safe(term_scope)}" data-term-shared="{_safe(term_scope + " " + " ".join(group["spellings"]))}"><h2>{_safe(group["term"])}</h2>'
                          f'<p class="meta">{_safe(term_scope)} · \u8bcd\u5f62 {spelling_count} \u79cd · \u91ca\u4e49 {len(variant_cards)} \u79cd · {spellings}</p>'
                          + ''.join(variant_cards) + '</article>')
    term_filters = '<label>解释状态 <select id="term-status"><option value="">全部</option><option value="candidate">候选</option><option value="active">已用于本群分析</option><option value="user">人工解释</option></select></label>'
    term_filters += '<label>解释依据 <select id="term-kind"><option value="">全部依据</option><option value="explicit">明确解释</option><option value="inferred">上下文推断</option><option value="ambiguous">含义有分歧</option><option value="unconfirmed">待确认</option></select></label>'
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


def _status(value, category=None):
    if value == 'open' and category in ('resource', 'transient', 'knowledge'):
        return {'resource': '资源待验证', 'transient': '状态观察', 'knowledge': '待确认'}[category]
    return {'open': '待解决', 'in_progress': '有新进展', 'resolved': '原消息有解决反馈',
            'disputed': '存在分歧'}.get(value, '待确认')


def _details(item):
    pieces = []
    quality = item.get('quality')
    if isinstance(quality, dict):
        basis = {'reproducible_method': '有具体步骤的方法', 'firsthand_result': '操作反馈',
                 'resource_lead': '资源线索', 'announcement': '公告', 'service_status': '服务状态',
                 'personal_opinion': '个人观点', 'promotion': '推广', 'request': '待解决请求',
                 'unsupported': '依据不足'}.get(quality.get('basis'), '依据待确认')
        pieces.append('<p>收录依据：' + _safe(basis) + '</p>')
        if item.get('quality_reason') == 'insufficient_source_grounding_for_high':
            pieces.append('<p class="meta">具体条件、步骤或结果依据尚不足，保留为候选。</p>')
        quote = quality.get('result_quote')
        if isinstance(quote, dict):
            pieces.append('<p>内容依据 #' + _safe(quote.get('message_id')) + '：</p><pre>' + _safe(quote.get('quote')) + '</pre>')
    if item.get('known'):
        pieces.append('<p><strong>已知内容</strong></p><pre>' + _safe(item['known']) + '</pre>')
    if item.get('missing'):
        pieces.append('<p><strong>还缺什么</strong></p><pre>' + _safe(item['missing']) + '</pre>')
    if item.get('source_time'):
        pieces.append('<p class="meta">最近来源时间：' + _time(item['source_time']) + '</p>')
    lifecycle = item.get('lifecycle')
    if isinstance(lifecycle, dict):
        pieces.append('<p class="meta">处理队列：' + _safe({'knowledge': '知识', 'followup': '待跟进', 'archive': '归档'}.get(lifecycle.get('lane'), '待确认')) + ' · '
                      + _safe(lifecycle.get('reason')) + '</p>')
        if lifecycle.get('last_progress_at'):
            pieces.append('<p class="meta">原消息进展时间：' + _time(lifecycle['last_progress_at']) + '</p>')
        if lifecycle.get('expires_at'):
            pieces.append('<p class="meta">保留截止时间：' + _time(lifecycle['expires_at'])
                          + (' · 已归档，仍未表示问题已解决' if lifecycle.get('archived') else '') + '</p>')
        elif lifecycle.get('archived'):
            pieces.append('<p class="meta">人工归档；归档不代表问题已解决。</p>')
    organization = item.get('organization') if isinstance(item.get('organization'), dict) else {}
    subject = organization.get('subject') if isinstance(organization.get('subject'), dict) else {}
    if subject.get('ambiguous'):
        pieces.append('<p class="meta">对象指代待确认</p>')
    resource = item.get('resource') or {}
    if resource:
        pieces.append('<p>资源：' + _safe(resource.get('name')) + ' · 未验证线索</p><pre>'
                      + _safe(resource.get('purpose')) + '\n' + _safe(resource.get('feedback')) + '</pre>')
        url = resource.get('url', '')
        if url.startswith(('https://', 'http://')):
            pieces.append('<p><a rel="noreferrer" href="' + _safe(url) + '">原消息中的资源链接</a></p>')
    return ''.join(pieces)


def _time(value):
    try:
        when = datetime.fromisoformat(value or '')
        if when.tzinfo is not None:
            return when.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S') + '（北京时间）'
    except (TypeError, ValueError):
        pass
    return '原始时间未知'

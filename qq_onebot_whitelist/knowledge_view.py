"""Render separated, local-only knowledge report pages."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from .content_utils import redact_secrets
from .knowledge_evidence import render_evidence
from .knowledge_layers import CATEGORIES, category_for
from .knowledge_lifecycle import lifecycle_for
from .knowledge_organization import TOPICS
from .knowledge_subjects import subjects_for, subject_id, UNASSIGNED
from .knowledge_tags import topic_tags_for
from .knowledge_usage import USAGE_TAGS, scope_catalog, usage_for, usage_markup


PAGES = (
    ("knowledge.html", "知识", "knowledge.html"),
    ("glossary.html", "术语", "glossary.html"),
    ("knowledge-summary.html", "总结", "knowledge-summary.html"),
    ("knowledge-files.html", "保留文件", "knowledge-files.html"),
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
    return '<nav class="report-nav" aria-label="报告分类">' + ''.join(links) + '</nav>'


def _excerpt(value, limit=240):
    text = redact_secrets(str(value or '').strip())
    return '<p class="card-excerpt">' + _safe(text[:limit] + ('…' if len(text) > limit else '')) + '</p>' if text else ''


def _content_tag_names(row):
    """Return bounded, deduplicated broad topic labels for a record."""
    return list(dict.fromkeys(_safe_name(name) for name in topic_tags_for(row) if _safe_name(name)))[:8]


def _safe_name(value):
    return redact_secrets(str(value or '').strip())[:80]


def _entity_markup(names):
    if not names:
        return ''
    return '<div class="content-tags" aria-label="对象标签">' + ''.join(
        '<span class="content-tag entity-tag">' + _safe(name) + '<small>对象</small></span>' for name in names) + '</div>'


def _unassigned_note(rows):
    notes = list(dict.fromkeys(str((row.get('organization') or {}).get('classification_note') or '')
                              for row in rows if isinstance(row.get('organization'), dict)))
    notes = [note for note in notes if note]
    return '<p class="meta">分类待确认：' + _safe('；'.join(notes)[:500]) + '</p>' if notes else ''


def _background_reference():
    from .knowledge_background import load_background
    data = load_background()
    entries = []
    for entry in data['entries']:
        aliases = []
        for alias in entry.get('aliases', []):
            state = {'standard': '标准称呼', 'conventional': '常见称呼', 'contextual': '需语境', 'candidate': '有歧义'}.get(alias.get('status'), '待核对')
            aliases.append(str(alias.get('text') or '') + '（' + state + '）')
        links = [url for url in entry.get('sources', []) if isinstance(url, str) and urlparse(url).scheme == 'https']
        references = ' · '.join('<a href="' + _safe(url) + '">' + _safe(urlparse(url).netloc) + '</a>' for url in links)
        entries.append('<section><h3>' + _safe(entry['canonical']) + '</h3><p>' + _safe(entry['definition']) + '</p>'
                       + '<p class="meta">' + _safe('、'.join(aliases)) + '</p><p class="meta">边界：' + _safe(entry['limits']) + '</p>'
                       + ('<p class="meta">参考来源：' + references + '</p>' if references else '<p class="meta">通用阅读提示，尚无独立参考来源。</p>') + '</section>')
    return '<details class="background-reference"><summary>分类参考：互联网常识与谐音（' + str(len(entries)) + ' 组）</summary>' \
        + '<p>本地背景词典 · 更新 ' + _safe(data['updated_at']) + '。帮助理解和分类，不能替代原消息证据；本群已确认的定义优先。</p>' \
        + ''.join(entries) + '</details>'


def _content_tag_markup(row):
    org = row.get('organization') if isinstance(row.get('organization'), dict) else {}
    tags = org.get('topic_tags') if isinstance(org.get('topic_tags'), list) else []
    tags_by_name = {}
    for tag in tags[:8]:
        if not isinstance(tag, dict) or not isinstance(tag.get('name'), str):
            continue
        name = _safe_name(tag['name'])
        if name:
            tags_by_name.setdefault(name, []).append(tag)
    names = _content_tag_names(row)
    if not names:
        return '', []
    chips = ''.join('<span class="content-tag">' + _safe(name) + '<small>AI归类</small></span>' for name in names)
    evidence_rows, seen_evidence = [], set()
    for name in names:
        for tag in tags_by_name.get(name, []):
            for ev in tag.get('evidence', [])[:3] if isinstance(tag.get('evidence'), list) else []:
                if (not isinstance(ev, dict) or type(ev.get('message_id')) is not int
                        or ev.get('message_id') <= 0 or not isinstance(ev.get('quote'), str)):
                    continue
                quote = redact_secrets(ev['quote'].strip())[:240]
                key = (name, ev.get('message_id'), quote, '附件名' if ev.get('source_field') == 'file_name' else '原文')
                if quote and key not in seen_evidence:
                    seen_evidence.add(key)
                    evidence_rows.append(key)
    evidence = ''
    if evidence_rows:
        evidence = '<details class="content-tag-evidence"><summary>查看主题归类依据</summary>' + ''.join(
            '<p><strong>' + _safe(name) + '</strong> · 原消息 #' + _safe(mid) + ' · ' + _safe(source_field) + '</p><blockquote>' + _safe(quote) + '</blockquote>'
            for name, mid, quote, source_field in evidence_rows[:12]) + '</details>'
    return '<div class="content-tags" aria-label="资料主题">' + chips + '</div>' + evidence, names


def _frame(filename: str, title: str, cards: list[str], groups: set[str], filters: str, subject_groups=None, subject_index=None) -> str:
    from .knowledge_presentation import STYLE, SCRIPT
    opts = ''.join(f'<option value="{_safe(group)}">{_safe(group.removeprefix("group:"))}</option>' for group in sorted(groups))
    count = len(cards)
    descriptions = {
        'knowledge.html': '可按平台、工具等对象，以及闲鱼、虚拟卡等资料主题查找，再看额度、接入、故障等具体情形。资料主题是 AI 归类，展开卡片可核对原消息依据；标签不表示当前使用成功。用途标签说明对象类型，不代表效果已验证。同主题的不同经历分别保留，未解决的问题在“待跟进”中查看。文字讨论可独立收录，不要求图片或附件。',
        'glossary.html': '遇到不熟悉的行业说法，先查释义，再展开原消息核对。同词的不同解释分别保留。',
        'knowledge-summary.html': '按批次回顾群里讨论了什么，再查看原消息了解细节。',
        'knowledge-files.html': '查看已整理的保留文件及保存状态；全部采集文件可从资料中心打开。',
    }
    empty = ('<div class="empty"><strong>本页暂无正式资料。</strong>'
             '<p>若已完成历史分析，请先发布整理结果。</p>'
             '<p>如需持续整理，可在管理器的“采集 → 群知识”配置群并启用相应功能；启用功能不会自动生成现有资料。</p>'
             '<p>查看已有资料无需启用自动分析。</p></div>')
    content = ''.join(cards) if cards else empty
    queues = ''
    if filename == 'knowledge.html':
        lane_counts = {lane: sum(f'data-lane="{lane}"' in card for card in cards) for lane in ('knowledge', 'followup', 'archive')}
        queues = '<div class="queues" role="group" aria-label="资料处理队列">' + ''.join(
            f'<button type="button" data-lane-target="{lane}" aria-pressed="{str(lane == "knowledge").lower()}">{label}<span class="queue-count">{lane_counts.get(lane,count)}</span></button>'
            for lane,label in [('knowledge','知识'),('followup','待跟进'),('archive','已归档'),('','全部')]) + '</div>'
        filters = filters.replace('<label>处理队列', '<label class="screen-reader">处理队列')
    sidebar = ''
    background_reference = _background_reference() if filename == 'knowledge.html' else ''
    if subject_groups:
        content = ''.join('<section class="subject-section" data-subject-group="' + subject_id(name) + '">'
            + '<header class="subject-heading"><h2>' + _safe(name) + '</h2><span data-subject-visible-count>'
            + str(len(cases)) + '</span><span data-related-context hidden></span></header><div class="subject-cases">' + ''.join(cases) + '</div></section>'
            for name, cases in subject_groups)
        sidebar = '<aside class="subject-sidebar"><h2>主题目录</h2><p>按平台、工具或资料主题浏览相关情形。资料主题由 AI 归类，跨主题讨论只保留一份；“对象待确认”只表示事件中的实体指代未明。</p><nav id="subject-nav" aria-label="按主题浏览">'
        sidebar += '<button type="button" data-subject-target="" data-subject-name="全部主题" aria-pressed="true">全部主题<span data-subject-count>' + str(count) + '</span></button>'
        sidebar += ''.join('<button type="button" data-subject-target="' + subject_id(name)
            + '" data-subject-name="' + _safe(name) + '" aria-pressed="false">' + _safe(name)
            + '<span data-subject-count>' + str(size) + '</span></button>' for name, size in subject_index)
        sidebar += '</nav></aside>'
    listing = f'''<div class="result-line"><span>找到 <strong id="shown-count">{count}</strong> 项</span><span>展开详情可查看原消息与整理依据</span></div>
<main id="results">{content}</main><div id="filter-empty" class="empty" hidden><strong>没有符合条件的资料</strong><p>试试更短的关键词，或清除筛选条件。</p></div>
<div class="pager"><button type="button" id="previous-page">上一页</button><span id="page-info" aria-live="polite"></span><button type="button" id="next-page">下一页</button></div>'''
    if sidebar:
        listing = '<div class="knowledge-layout">' + sidebar + '<div class="knowledge-content">' + listing + '</div></div>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · 群资料库</title>
<style>{STYLE}</style></head><body class="{'knowledge-page' if filename == 'knowledge.html' else 'report-page'}"><a class="skip-link" href="#results">跳到资料列表</a>
<header id="report-top" class="site-header"><div class="header-inner"><a class="brand" href="knowledge.html">群资料库<small>从群聊中整理，回到原文中核对</small></a>{_nav(filename)}</div></header>
<div class="shell"><div class="page-heading"><h1>{title}</h1><p class="page-intro">{descriptions[filename]}</p><span class="page-total">本页共 {count} 项</span>{queues}</div>
<section class="toolbar" aria-label="查找资料"><div class="search-row"><label class="search-label"><span>搜索</span><input id="search" type="search" placeholder="输入关键词查找本页资料" aria-label="搜索本页内容" autocomplete="off"></label><button type="button" id="clear-filters" class="clear-button">清除筛选</button></div>
<div class="filters"><label>群组 <select id="group"><option value="">全部群</option>{opts}</select></label>{filters}</div></section>
{listing}{background_reference}
<footer><a class="back-top" href="#report-top">回到顶部 ↑</a>本地整理报告 · 群友说法与已验证反馈会分别标注；来源编号用于回查原消息。</footer></div>
<script>{SCRIPT}</script></body></html>'''



def render_views(data_dir: Path, *, items: list[dict], runs: list[dict], assets: list[dict],
                 glossary: list[dict], threads: list[dict] | None = None,
                 profiles: dict | None = None, manual_archives: dict | None = None,
                 now=None, subject_catalog=()) -> dict[str, str]:
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

    knowledge_cards, case_subjects, used_tags = [], [], set()

    def usage_attributes(entries):
        tags = list(dict.fromkeys(entry['tag'] for entry in entries))
        used_tags.update(tags)
        return 'data-usage-tags="' + ','.join(tags) + '" data-usage-names="' + _safe(' / '.join(USAGE_TAGS[tag] for tag in tags)) + '"'
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
        entities = subjects_for(item, scope_catalog(subject_catalog, item.get('scope')))
        tag_markup, tag_names = _content_tag_markup(item)
        names = list(dict.fromkeys([*entities, *tag_names])) or [UNASSIGNED]
        name = names[0] if names else UNASSIGNED
        case_subjects.append(names)
        usages = usage_for(item, subject_catalog)
        knowledge_cards.append(
            f'<article {usage_attributes(usages)} data-subject="{subject_id(name)}" data-subjects="{",".join(subject_id(n) for n in names)}" data-subject-name="{_safe(" / ".join(names))}" data-group="{_safe(item.get("scope"))}" data-value="{val}" data-category="{category}" data-lane="{lifecycle["lane"]}" data-topics="{_safe(",".join(topic_ids))}">'
            f'<h2>{_safe(item.get("title"))}</h2>' + _entity_markup(entities) + usage_markup(usages) + tag_markup
            + (_unassigned_note([item]) if names == [UNASSIGNED] else '') + f'<p class="meta">涉及对象/资料主题：{_safe(" / ".join(names))} · 情形：{_safe("、".join(TOPICS.get(t,t) for t in topic_ids))}</p><p class="meta">{_safe(item.get("scope"))} · {_safe(item.get("created_at"))} · '
            f'{_safe(item.get("topic"))} · {_safe(item.get("kind"))} · '
            f'{CATEGORIES[category]} · {"精选" if val == "high" else "待确认"} · {state} · {msgrefs}</p>'
            + _excerpt(item.get('body', item.get('summary')))
            + '<details><summary>查看完整内容与依据</summary>'
            + f'<pre>{_safe(item.get("body", item.get("summary")))}</pre>{_details({**item, "lifecycle": lifecycle})}{evidence(item.get("scope"), ids)}'
            + f'{_feedback_controls(item)}</details></article>')
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
        catalog = scope_catalog(subject_catalog, thread['scope'])
        entities = list(dict.fromkeys(name for event in reversed(events) for name in subjects_for(event, catalog)))
        tag_names = list(dict.fromkeys(name for event in events for name in _content_tag_names(event)))
        tag_markup, _ = _content_tag_markup({'organization': {'topic_tags': [tag for event in events
            for tag in ((event.get('organization') or {}).get('topic_tags', []) if isinstance(event.get('organization'), dict) else [])]}})
        names = list(dict.fromkeys([*entities, *tag_names])) or [UNASSIGNED]
        name = names[0] if names else UNASSIGNED
        case_subjects.append(names)
        usages = []
        for event in reversed(events):
            for entry in usage_for({**event, 'scope': thread['scope']}, subject_catalog):
                if not any((r['subject'], r['tag']) == (entry['subject'], entry['tag']) for r in usages):
                    usages.append(entry)
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
        progress_label = _status(thread['status'], category)
        labels = list(dict.fromkeys([CATEGORIES[category], '精选' if val == 'high' else '待确认', state_label, progress_label]))
        knowledge_cards.append(f'<article {usage_attributes(usages)} data-subject="{subject_id(name)}" data-subjects="{",".join(subject_id(n) for n in names)}" data-subject-name="{_safe(" / ".join(names))}" data-group="{_safe(thread["scope"])}" data-value="{val}" data-category="{category}" data-lane="{lifecycle["lane"]}" data-topics="{_safe(",".join(topic_ids))}">'
            f'<h2>{_safe(thread["title"])}</h2>' + _entity_markup(entities) + usage_markup(usages) + tag_markup
            + (_unassigned_note(events) if names == [UNASSIGNED] else '') + f'<p class="meta">涉及对象/资料主题：{_safe(" / ".join(names))} · 情形：{_safe("、".join(TOPICS.get(t,t) for t in topic_ids))}</p><p class="meta">{" · ".join(labels)} · 话题记录 {len(events)} 次</p>'
            + _excerpt(thread.get('known') or (events[-1].get('summary') if events else ''))
            + '<details><summary>查看整理内容与缺少信息</summary>'
            + _details({'known': thread.get('known'), 'missing': thread.get('missing'), 'source_time': thread.get('source_time'),
                        'resource': thread.get('resource'), 'quality': latest.get('quality'),
                        'quality_reason': latest.get('quality_reason'), 'lifecycle': lifecycle}) + '</details>'
            + '<details><summary>查看讨论进展与证据</summary>' + ''.join(timeline) + '</details></article>')
    knowledge_filters = '<label>处理队列 <select id="lane"><option value="knowledge">知识</option><option value="followup">待跟进</option><option value="archive">归档</option><option value="">全部</option></select></label>'
    grouped_cases, subject_counts = {}, {}
    for names, card in zip(case_subjects, knowledge_cards):
        grouped_cases.setdefault(names[0], []).append(card)
        for name in names:
            subject_counts[name] = subject_counts.get(name, 0) + 1
    subject_groups = sorted(grouped_cases.items(), key=lambda pair: (pair[0] == UNASSIGNED, -len(pair[1]), pair[0]))
    subject_index = sorted(subject_counts.items(), key=lambda pair: (pair[0] == UNASSIGNED, -pair[1], pair[0]))
    knowledge_filters += '<label class="screen-reader">主题 <select id="subject"><option value="">全部主题</option>' + ''.join(
        f'<option value="{subject_id(name)}">{_safe(name)}</option>' for name, _ in subject_index) + '</select></label>'
    knowledge_filters += '<label>情形类型 <select id="topic"><option value="">全部情形</option>' + ''.join(
        f'<option value="{_safe(key)}">{_safe(label)}</option>' for key, label in TOPICS.items()) + '</select></label>'
    knowledge_filters += '<label>用途标签 <select id="usage-tag"><option value="">全部用途</option>' + ''.join(
        f'<option value="{key}">{USAGE_TAGS[key]}</option>' for key in USAGE_TAGS if key in used_tags) + '</select></label>'
    knowledge_filters += '<details class="more-filters"><summary>更多筛选</summary><div><label>资料类型 <select id="category"><option value="">全部类型</option>' + ''.join(
        f'<option value="{key}">{label}</option>' for key, label in CATEGORIES.items()) + '</select></label>'
    knowledge_filters += '<label>价值 <select id="value"><option value="">全部知识</option><option value="high">精选讨论</option><option value="candidate">待确认讨论</option></select></label>'
    knowledge_filters += '</div></details>'
    knowledge_html = _frame("knowledge.html", "群知识", knowledge_cards, groups, knowledge_filters, subject_groups, subject_index)
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
                                  f'<h3>{_safe(explanation)}</h3><p class="meta">{label} · {reftext}</p><details><summary>查看释义依据与原文</summary>{annotation}{evidence(term_scope, ids)}</details></section>')
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

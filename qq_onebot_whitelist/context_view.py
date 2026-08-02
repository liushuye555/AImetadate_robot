from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone
import html
import json
import sqlite3
from urllib.parse import quote

from .content_utils import redact_secrets
from .html_render import render_markdown
from .scope_names import display_scope


PAGE_STYLE = '''
:root{color-scheme:dark}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:22px;background:#0d0f13;color:#eef1f6}a{color:#9fc2ff}.muted{color:#aab2c0}.badge{display:inline-block;padding:3px 8px;border-radius:999px;background:#533d18;color:#ffd98a;font-size:13px}.markdown{line-height:1.65;background:#151922;padding:16px 20px;border-radius:12px;overflow-wrap:anywhere}.markdown pre,pre{white-space:pre-wrap;overflow:auto;background:#090b0f;padding:12px;border-radius:9px}.markdown code{background:#272d38;padding:.12em .35em;border-radius:4px}.markdown table{border-collapse:collapse;width:100%}.markdown th,.markdown td{border:1px solid #394150;padding:8px;text-align:left}.table-wrap{overflow:auto}.markdown blockquote{margin:1em 0;padding:.2em 1em;border-left:4px solid #668bc4;color:#c7cfdb}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:20px}.card{padding:14px;background:#171a21;border:1px solid #2b313d;border-radius:14px}.card img{width:100%;max-height:65vh;object-fit:contain;background:#000;border-radius:10px}details{margin-top:10px}summary{cursor:pointer}
'''


def _url_path(path: str) -> str:
    return '/'.join(quote(part) for part in path.replace('\\', '/').split('/'))


def _batch_state(raw_json: str | None) -> tuple[str, bool]:
    try:
        raw = json.loads(raw_json or '{}')
        quality = raw.get('quality') or {}
        value = quality.get('value_level')
        hidden = bool(raw.get('hidden'))
    except (AttributeError, TypeError, ValueError):
        value = None
        hidden = False
    return (value if value in {'high', 'review', 'low'} else 'review', hidden)


def _date(value: object) -> str:
    text = str(value or '').strip()
    if len(text) < 10:
        return '日期未知'
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime('%Y-%m-%d')
    except ValueError:
        return text[:10]


def _scope_key(scope: str) -> str:
    return ''.join(character if character.isalnum() else '_' for character in scope).strip('_') or 'unknown'


def _document(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        f'<title>{html.escape(title)}</title><style>{PAGE_STYLE}</style><body>{body}</body></html>'
    )


def _load_batches(conn: sqlite3.Connection) -> list[dict[str, object]]:
    try:
        rows = conn.execute(
            '''SELECT id, created_at, scope, start_message_id, end_message_id, model, summary, raw_json
               FROM ai_context_batches ORDER BY id DESC'''
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    result = []
    for row in rows:
        quality, hidden = _batch_state(row['raw_json'])
        result.append({
            'id': int(row['id']),
            'created_at': str(row['created_at'] or ''),
            'scope': str(row['scope'] or ''),
            'start_message_id': int(row['start_message_id']),
            'end_message_id': int(row['end_message_id']),
            'model': str(row['model'] or ''),
            'summary': str(row['summary'] or ''),
            'quality': quality,
            'hidden': hidden,
        })
    return result


def _image_cards(items: list[dict[str, object]], prefix: str) -> str:
    if not items:
        return '<p class="muted">此页没有关联图片。</p>'
    cards = []
    for item in items:
        image_url = _url_path(prefix + str(item['image_rel']))
        cards.append(
            '<article class="card">'
            f'<a href="{html.escape(image_url)}"><img src="{html.escape(image_url)}" loading="lazy"></a>'
            f'<p>#{html.escape(str(item["id"]))} · {html.escape(str(item["meta"]))}</p>'
            '<details><summary>查看图片附近原始上下文</summary>'
            f'<pre>{html.escape(redact_secrets(str(item.get("text_excerpt") or "无")))}</pre></details>'
            '</article>'
        )
    return '<div class="images">' + ''.join(cards) + '</div>'


def _write_batch_page(path: Path, batch: dict[str, object], items: list[dict[str, object]], scope_name: str) -> None:
    body = (
        f'<h1>{html.escape(scope_name)} · 批次 #{batch["id"]}</h1>'
        f'<p class="muted">{html.escape(_date(batch["created_at"]))} · 消息 '
        f'{batch["start_message_id"]}–{batch["end_message_id"]} · {html.escape(str(batch["model"]))}</p>'
        f'<div class="markdown">{render_markdown(redact_secrets(str(batch["summary"] or "暂无批摘要")))}</div>'
        + _image_cards(items, '../')
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_document(f'批次 #{batch["id"]}', body), encoding='utf-8')


def _write_history_page(path: Path, items: list[dict[str, object]], scope_name: str, date: str) -> None:
    body = (
        f'<h1>{html.escape(scope_name)} · {html.escape(date)} 历史图片</h1>'
        '<p class="muted">这些旧图片没有 message_db_id，仅按群和日期归档，不关联任何批次摘要。</p>'
        + _image_cards(items, '../../')
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_document(f'{scope_name} {date} 历史图片', body), encoding='utf-8')


def _directory(groups: dict[tuple[str, str], list[tuple[str, str, str]]]) -> tuple[str, str]:
    sections = []
    first_target = ''
    for quality, heading in (('high', '可复用参数'), ('history', '历史图片')):
        scope_blocks = []
        for (item_quality, scope_name), entries in sorted(groups.items()):
            if item_quality != quality:
                continue
            date_blocks = []
            by_date: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for date, label, href in entries:
                by_date[date].append((label, href))
                if not first_target:
                    first_target = href
            for date, links in sorted(by_date.items(), reverse=True):
                link_html = ''.join(
                    f'<li><a href="{html.escape(_url_path(href))}" target="context-frame">{html.escape(label)}</a></li>'
                    for label, href in links
                )
                date_blocks.append(f'<details><summary>{html.escape(date)}</summary><ul>{link_html}</ul></details>')
            scope_blocks.append(
                f'<details open><summary>{html.escape(scope_name)}</summary>{"".join(date_blocks)}</details>'
            )
        if scope_blocks:
            sections.append(f'<section><h2>{heading}</h2>{"".join(scope_blocks)}</section>')
    return ''.join(sections) or '<p class="muted">暂无可展示的上下文记录。</p>', first_target


def build_context_view(
    conn: sqlite3.Connection,
    context_dir: Path,
    items: list[dict[str, object]],
    group_names: dict[str, str],
) -> None:
    batches = _load_batches(conn)
    visible_batches = [
        batch for batch in batches
        if batch['quality'] == 'high' and not batch['hidden'] and str(batch['summary']).strip()
    ]
    batch_images: dict[int, list[dict[str, object]]] = defaultdict(list)
    history_images: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        matched = None
        message_db_id = item.get('message_db_id')
        if message_db_id is not None:
            matched = next(
                (
                    batch for batch in visible_batches
                    if batch['scope'] == item['scope']
                    and int(batch['start_message_id']) <= int(message_db_id) <= int(batch['end_message_id'])
                ),
                None,
            )
        if matched is not None:
            batch_images[int(matched['id'])].append(item)
        else:
            history_images[(str(item['scope']), _date(item.get('seen_at')))].append(item)

    context_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for batch in visible_batches:
        scope = str(batch['scope'])
        scope_name = display_scope(scope, group_names)
        href = f'batches/{batch["id"]}.html'
        _write_batch_page(context_dir / href, batch, batch_images[int(batch['id'])], scope_name)
        groups[(str(batch['quality']), scope_name)].append(
            (_date(batch['created_at']), f'批次 #{batch["id"]}', href)
        )

    for (scope, date), page_items in history_images.items():
        scope_name = display_scope(scope, group_names)
        href = f'history/{_scope_key(scope)}/{date}.html'
        _write_history_page(context_dir / href, page_items, scope_name, date)
        groups[('history', scope_name)].append((date, f'{len(page_items)} 张图片', href))

    directory, first_target = _directory(groups)
    if not first_target:
        first_target = 'empty.html'
        (context_dir / first_target).write_text(
            _document('暂无上下文', '<h1>暂无可展示的上下文记录</h1>'), encoding='utf-8'
        )
    index = _document(
        '03_AI上下文',
        '<main class="layout"><nav><h1>03_AI上下文</h1>' + directory + '</nav>'
        f'<iframe name="context-frame" src="{html.escape(_url_path(first_target))}" title="上下文详情"></iframe></main>'
        '<style>.layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:16px;height:calc(100vh - 44px)}nav{overflow:auto;padding-right:10px}nav h1{font-size:22px}nav h2{font-size:16px;margin-top:20px}nav details details{margin-left:12px}nav ul{margin:8px 0;padding-left:22px}iframe{width:100%;height:100%;border:1px solid #2b313d;border-radius:12px;background:#0d0f13}@media(max-width:760px){body{padding:12px}.layout{grid-template-columns:1fr;height:auto}nav{max-height:42vh}iframe{height:70vh}}</style>',
    )
    (context_dir / 'index.html').write_text(index, encoding='utf-8')

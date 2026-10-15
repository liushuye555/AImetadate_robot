"""Render complete, group-local source evidence for the knowledge view."""
from __future__ import annotations

from html import escape
from pathlib import Path

from .content_utils import redact_secrets
from .knowledge_store import read_records


def _speaker_label(aliases: dict[str, str], actor_key: str | None) -> str:
    if not actor_key:
        return '成员未知'
    if actor_key not in aliases:
        aliases[actor_key] = '成员' + str(len(aliases) + 1)
    return aliases[actor_key]


def _render_one(data_dir: Path, scope: str, message_id: int, aliases: dict[str, str]) -> str:
    rows = read_records(data_dir / 'bot.db', scope, after_id=message_id - 1,
                        before_id=message_id, limit=1)
    if not rows:
        return f'<p>#{message_id} · 原记录不可用</p>'

    record = rows[0]
    speaker = _speaker_label(aliases, record.get('actor_key'))
    when = record.get('time') or '时间未知'
    pieces = [
        f'<p>#{message_id} · {escape(str(when))} · {escape(speaker)}</p>',
        f'<pre>{escape(redact_secrets(record.get("text") or ""))}</pre>',
    ]
    quoted_text = record.get('quoted_text') or ''
    if quoted_text:
        quoted_speaker = _speaker_label(aliases, record.get('quoted_actor_key'))
        quoted_id = record.get('quoted_id')
        quoted_number = f'#{quoted_id}' if quoted_id is not None else '编号不可用'
        pieces.extend((
            f'<p>引用 {quoted_number} · {escape(quoted_speaker)}：</p>',
            f'<pre>{escape(redact_secrets(quoted_text))}</pre>',
        ))
    return ''.join(pieces)


def render_evidence(data_dir: Path, scope: str, ids: list[int]) -> str:
    """Return expandable HTML for every referenced message in the given group.

    The first six sources remain directly visible inside the outer disclosure;
    any further sources are available in a nested disclosure.
    """
    valid_ids = [message_id for message_id in ids if type(message_id) is int and message_id > 0]
    aliases: dict[str, str] = {}
    visible = ''.join(_render_one(data_dir, scope, mid, aliases) for mid in valid_ids[:6])
    if len(valid_ids) > 6:
        remaining = ''.join(_render_one(data_dir, scope, mid, aliases) for mid in valid_ids[6:])
        visible += (f'<details><summary>展开其余 {len(valid_ids) - 6} 条来源</summary>'
                    f'{remaining}</details>')
    return '<details><summary>展开原消息证据</summary>' + visible + '</details>'

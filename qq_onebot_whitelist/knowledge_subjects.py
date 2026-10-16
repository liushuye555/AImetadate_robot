"""Source-grounded subject labels for browsing; never merge case histories."""
from __future__ import annotations

from hashlib import sha256
import re
import unicodedata

from .content_utils import redact_secrets


UNASSIGNED = '其他与对象待确认'
# These are navigation labels, not evidence about a vendor or product's behavior.
ALIASES = {
    '智谱': ('智谱', 'zhipu', 'z.ai', 'glm'),
    'DeepSeek': ('deepseek', 'ds'),
    'WorkBuddy': ('workbuddy', 'work buddy', 'wb', 'wk ai'),
    'OpenCode': ('opencode', 'open code'),
    'OpenDesign': ('opendesign', 'open design'),
    'Claude': ('claude', 'opus', 'sonnet'),
    'ChatGPT / OpenAI': ('chatgpt', 'openai', 'gpt'),
    '通义 / Qwen': ('通义', '千问', 'qwen'),
    'Gemini': ('gemini',),
    'DSh / Infinite Gen': ('dsh', 'dsh-infinite-gen', 'infinite gen', 'ig5'),
}


def _normalized(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold().strip()


def _mentions(text, alias):
    text, alias = _normalized(text), _normalized(alias)
    # Product version suffixes count as mentions; substrings of unrelated
    # English words do not (e.g. "ds" inside a domain or "words").
    if alias.isascii():
        return re.search(r'(?<![a-z0-9_])' + re.escape(alias) + r'(?![a-z_])', text) is not None
    return alias in text


def canonical_subject(name):
    value = redact_secrets(str(name or '').strip())[:64]
    for label, aliases in ALIASES.items():
        if _normalized(value) == _normalized(label) or any(_mentions(value, alias) for alias in aliases):
            return label
    return value


def subject_id(name):
    return sha256(_normalized(name).encode()).hexdigest()[:16]


def prepare_subjects(raw, item, records):
    """Keep only labels with an exact quote and an actual subject mention."""
    if not isinstance(raw, list):
        return []
    allowed = set(item.get('evidence_ids', []))
    sources = {row['id']: [str(row.get('text') or '')] + [str(file['preview'].get('text') or '')
        for file in row.get('files', []) if isinstance(file, dict) and isinstance(file.get('preview'), dict)]
        for row in records if row.get('id') in allowed}
    for row in records:
        if row.get('quoted_id') in allowed:
            sources.setdefault(row['quoted_id'], [str(row.get('quoted_text') or '')])
    by_name = {}
    for candidate in raw[:6]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get('name'), str):
            continue
        name = canonical_subject(candidate['name'])
        if not name or len(candidate['name']) > 100:
            continue
        quotes = candidate.get('evidence')
        if not isinstance(quotes, list):
            continue
        for quote in quotes[:4]:
            if not isinstance(quote, dict):
                continue
            mid, text = quote.get('message_id'), quote.get('quote')
            if type(mid) is not int or mid not in sources or not isinstance(text, str) or not text.strip():
                continue
            text = text.strip()
            if not any(text in source for source in sources[mid]):
                continue
            aliases = ALIASES.get(name, (name,))
            if not any(_mentions(text, alias) for alias in aliases):
                continue
            entry = by_name.setdefault(name, {'name': name, 'evidence': []})
            clean = {'message_id': mid, 'quote': redact_secrets(text)[:500]}
            if clean not in entry['evidence']:
                entry['evidence'].append(clean)
    return list(by_name.values())[:3]


def subjects_for(row):
    org = row.get('organization') if isinstance(row.get('organization'), dict) else {}
    if isinstance(org.get('subjects'), list) and (org['subjects'] or org.get('subjects_complete') is not False):
        return list(dict.fromkeys(canonical_subject(entry.get('name')) for entry in org['subjects']
            if isinstance(entry, dict) and entry.get('name') and entry.get('evidence')))
    legacy = org.get('subject')
    if isinstance(legacy, dict) and legacy.get('name') and legacy.get('ambiguous') is not True:
        return [canonical_subject(legacy['name'])]
    return []

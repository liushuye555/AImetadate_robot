"""Source-grounded subject labels for browsing; never merge case histories."""
from __future__ import annotations

from hashlib import sha256
import re
import unicodedata

from .content_utils import redact_secrets
from .knowledge_background import aliases_in_context, canonical_in_context, load_background


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
    'Infinite Gen': ('dsh-infinite-gen', 'infinite gen'),
    'IG5': ('ig5',),
    'DSh': ('dsh',),
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


def canonical_subject(name, catalog=()):
    value = redact_secrets(str(name or '').strip())[:64]
    for entry in catalog:
        if _normalized(value) == _normalized(entry['subject']) or any(
                _normalized(value) == _normalized(alias) for alias in entry.get('aliases', [])):
            return entry['subject']
    # The old combined navigation label is not a proven equivalence.
    if value == 'DSh / Infinite Gen':
        return value
    for label, aliases in ALIASES.items():
        if _normalized(value) == _normalized(label) or any(_mentions(value, alias) for alias in aliases):
            return label
    return value


def subject_id(name):
    return sha256(_normalized(name).encode()).hexdigest()[:16]


def prepare_subjects(raw, item, records, catalog=()):
    """Keep only labels with an exact quote and an actual subject mention."""
    if not isinstance(raw, list):
        return []
    allowed = set(item.get('evidence_ids', []))
    sources = {row['id']: [str(row.get('text') or '')] + [str(file.get('file_name') or '') for file in row.get('files', []) if isinstance(file, dict)] + [str(file['preview'].get('text') or '')
        for file in row.get('files', []) if isinstance(file, dict) and isinstance(file.get('preview'), dict)]
        for row in records if row.get('id') in allowed}
    for row in records:
        if row.get('quoted_id') in allowed:
            sources.setdefault(row['quoted_id'], [str(row.get('quoted_text') or '')])
    by_name = {}
    context = [text for texts in sources.values() for text in texts]
    for candidate in raw[:6]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get('name'), str):
            continue
        name = canonical_subject(candidate['name'], catalog)
        if not any(entry['subject'] == name for entry in catalog):
            name = canonical_subject(canonical_in_context(name, context), catalog)
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
            aliases = aliases_for(name, catalog, context)
            if not any(_mentions(text, alias) for alias in aliases):
                continue
            entry = by_name.setdefault(name, {'name': name, 'evidence': []})
            clean = {'message_id': mid, 'quote': redact_secrets(text)[:500]}
            if clean not in entry['evidence']:
                entry['evidence'].append(clean)
    return list(by_name.values())[:3]


def aliases_for(name, catalog=(), context=()):
    learned = [alias for entry in catalog if entry['subject'] == name for alias in entry.get('aliases', [])]
    claimed = {_normalized(alias) for entry in catalog if entry['subject'] != name
               for alias in (entry['subject'], *entry.get('aliases', []))}
    background = [alias for alias in aliases_in_context(name, context) if _normalized(alias) not in claimed]
    return tuple(dict.fromkeys((name, *ALIASES.get(name, ()), *learned, *background)))


def add_background_subjects(existing, item, records, catalog=()):
    """Supplement explicit platform/manual names, never infer an unnamed vendor."""
    names = [entry['canonical'] for entry in load_background()['entries'] if entry.get('kind') == 'entity']
    names.extend(entry['subject'] for entry in catalog)
    allowed = set(item.get('evidence_ids', []))
    sources = []
    for row in records:
        if row.get('id') in allowed:
            sources.append((row['id'], str(row.get('text') or '')))
            sources.extend((row['id'], str(file.get('file_name') or '')) for file in row.get('files', []) if isinstance(file, dict))
        if row.get('quoted_id') in allowed:
            sources.append((row['quoted_id'], str(row.get('quoted_text') or '')))
    result = list(existing)
    context = [text for _, text in sources]
    for name in dict.fromkeys(names):
        if any(entry['name'] == name for entry in result):
            continue
        quotes = [{'message_id': mid, 'quote': match.group(0)} for mid, text in sources
                  for alias in aliases_for(name, catalog, context) if _mentions(text, alias)
                  for match in [re.search(re.escape(alias), text, re.IGNORECASE)] if match]
        accepted = prepare_subjects([{'name': name, 'evidence': quotes}], item, records, catalog)
        if accepted:
            result.extend(accepted)
    return result[:3]


def _entry_names(entry, catalog):
    name = entry.get('name')
    if name != 'DSh / Infinite Gen':
        name = canonical_subject(name, catalog)
        if any(value['subject'] == name for value in catalog):
            if not any(isinstance(quote, dict) and any(_mentions(quote.get('quote', ''), alias)
                       for alias in aliases_for(name, catalog)) for quote in entry.get('evidence', [])):
                return []
        return [name]
    # Recover the actual name from each source quote, rather than carrying an
    # unsupported alias merge into the new directory.
    names = []
    for evidence in entry.get('evidence', []):
        text = evidence.get('quote', '') if isinstance(evidence, dict) else ''
        if any(_mentions(text, alias) for alias in ALIASES['Infinite Gen']):
            names.append('Infinite Gen')
        if _mentions(text, 'ig5'):
            names.append('IG5')
        standalone = re.sub(r'dsh-infinite-gen[^\s,，;；]*', '', _normalized(text))
        if _mentions(standalone, 'dsh'):
            names.append('DSh')
    return names


def subjects_for(row, catalog=()):
    org = row.get('organization') if isinstance(row.get('organization'), dict) else {}
    if isinstance(org.get('subjects'), list) and (org['subjects'] or org.get('subjects_complete') is not False):
        return list(dict.fromkeys(name for entry in org['subjects']
            if isinstance(entry, dict) and entry.get('name') and entry.get('evidence')
            for name in _entry_names(entry, catalog)))
    legacy = org.get('subject')
    if isinstance(legacy, dict) and legacy.get('name') and legacy.get('ambiguous') is not True:
        return _entry_names(legacy, catalog)
    return []

"""Maintained Internet context: hints for reading, never current-event evidence."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unicodedata


PATH = Path(__file__).with_name('knowledge_background.json')
SYSTEM = '''internet_background是分层的解释背景，不是本群原始证据，也不是本次操作结果。
其中稳定概念解释常见平台/技术，contextual别名只有满足上下文时才考虑，candidate歧义词只列候选含义。群内人工确认优先于通用背景；背景与本群用例冲突时保留歧义。
谐音、俗称、缩写应结合整段讨论、引用和本群已确认释义判断；词形相似不等于同一对象。不得将“国内号”猜成某个平台账号，或将“Visa”猜成具体发卡机构。
有资料主题但具体平台未知时保留主题标签；未知对象仍标明未确认。禁止把背景说明中的定义、价格、服务能力或限制写作本次群友实测。'''


def _norm(value):
    return unicodedata.normalize('NFKC', str(value)).casefold()


def load_background():
    value = json.loads(PATH.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('entries'), list):
        raise ValueError('互联网背景词典格式无效')
    return value


def background_fingerprint():
    return sha256(PATH.read_bytes()).hexdigest()


def aliases_in_context(name, texts):
    text = _norm('\n'.join(texts))
    result = []
    for entry in load_background()['entries']:
        if entry.get('canonical') != name or entry.get('kind') != 'entity':
            continue
        for alias in entry.get('aliases', []):
            if alias.get('status') == 'candidate':
                continue
            requires = alias.get('requires_any', [])
            if any(_norm(word) in text for word in alias.get('excludes_any', [])):
                continue
            if not requires or any(_norm(word) in text for word in requires):
                result.append(alias['text'])
    return result


def canonical_in_context(name, texts):
    for entry in load_background()['entries']:
        if entry.get('kind') == 'entity' and any(_norm(name) == _norm(alias)
                for alias in aliases_in_context(entry['canonical'], texts)):
            return entry['canonical']
    return name


def context_for(records):
    # Send only matching entries and the small list of explicitly ambiguous
    # terms. Nothing is fetched from the Internet during collection.
    text = _norm('\n'.join(str(row.get('text') or '') + '\n' + str(row.get('quoted_text') or '') for row in records))
    value = load_background()
    entries = []
    for entry in value['entries']:
        names = [entry['canonical'], *[alias['text'] for alias in entry.get('aliases', [])]]
        if any(_norm(name) in text for name in names):
            entries.append(entry)
    return {'version': value['version'], 'fingerprint': background_fingerprint(), 'entries': entries[:30]}

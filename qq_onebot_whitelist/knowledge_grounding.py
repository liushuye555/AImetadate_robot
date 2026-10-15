"""Conservative, source-backed eligibility for learned glossary meanings."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256


def definition_quotes(term: str, definitions: object, evidence: list[int], records: list[dict]) -> list[dict]:
    """Keep only exact, group-local excerpts attributed to cited messages."""
    if not isinstance(definitions, list) or len(definitions) > 60:
        return []
    sources = {r['id']: r for r in records}
    quotes = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        mid, quote = definition.get('message_id'), definition.get('quote')
        source = sources.get(mid) if type(mid) is int and mid in evidence else None
        if source is None or not isinstance(quote, str) or not quote.strip():
            continue
        quote = quote.strip()
        if quote not in source.get('text', '') or term.casefold() not in quote.casefold():
            continue
        quotes.append({'message_id': mid, 'quote': quote})
    return quotes


def definition_contexts(term: str, definitions: object, evidence: list[int], records: list[dict]) -> list[str]:
    """Count quoted definitions, never mere mentions or unknown timestamps."""
    sources = {r['id']: r for r in records}
    contexts = set()
    for definition in definition_quotes(term, definitions, evidence, records):
        source = sources[definition['message_id']]
        try:
            when = datetime.fromisoformat(source.get('time') or '')
            if when.tzinfo is None:
                continue
            stamp = int(when.timestamp())
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        digest = sha256(''.join(source['text'].casefold().split()).encode()).hexdigest()
        contexts.add(f'def2:{stamp}:{digest}')
    return sorted(contexts)


def independent_definitions(contexts: list[str]) -> bool:
    """Require definitions from nonidentical messages at least 30 minutes apart.

    Older hashes only recorded mentions and cannot establish learned meanings.
    This is an admission boundary, not a guarantee of semantic correctness.
    """
    parsed = []
    for value in contexts:
        if not isinstance(value, str):
            continue
        parts = value.split(':')
        if len(parts) != 3 or parts[0] != 'def2' or len(parts[2]) != 64:
            continue
        try:
            parsed.append((int(parts[1]), parts[2]))
        except ValueError:
            continue
    return any(a[1] != b[1] and abs(a[0] - b[0]) >= 1800
               for index, a in enumerate(parsed) for b in parsed[index + 1:])


def effective_term(term: dict) -> dict:
    """Do not reuse or display legacy mention-only activation as confirmed."""
    import json
    result = dict(term)
    try:
        contexts = json.loads(result.get('contexts_json') or '[]')
    except (ValueError, TypeError):
        contexts = []
    if (result.get('origin') != 'user' and result.get('status') == 'active'
            and (not isinstance(contexts, list) or not independent_definitions(contexts))):
        result['status'] = 'candidate'
    return result

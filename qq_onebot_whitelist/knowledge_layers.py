"""Separate durable knowledge, questions, resource leads and time-sensitive reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from .content_utils import redact_secrets


CATEGORIES = {'knowledge': '可复用知识', 'question': '待解决问题',
              'resource': '资源线索', 'transient': '时效信息'}


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS item_details (
        item_key TEXT PRIMARY KEY, category TEXT NOT NULL, known_text TEXT NOT NULL,
        missing_text TEXT NOT NULL, source_time TEXT, resource_json TEXT NOT NULL)''')


def category_for(item):
    category = item.get('category')
    if isinstance(category, str) and category in CATEGORIES:
        return category
    if item.get('evidence_state') == 'unresolved' or item.get('kind') in ('未解决', '未解决问题', 'question'):
        return 'question'
    if item.get('kind') in ('资源', 'resource'):
        return 'resource'
    return 'knowledge'


def prepare_details(row, records):
    if row.get('category') is not None and (not isinstance(row['category'], str) or row['category'] not in CATEGORIES):
        raise ValueError('AI 知识分类无效')
    ids = set(row['evidence_ids'])
    sources = [r for r in records if r['id'] in ids]
    stamps = []
    for source in sources:
        try:
            stamp = datetime.fromisoformat(source.get('time') or '')
            if stamp.tzinfo:
                stamps.append(stamp.astimezone(timezone.utc))
        except (ValueError, TypeError):
            pass
    result = {'category': category_for(row), 'source_time': max(stamps).isoformat() if stamps else None,
              'resource': {}}
    for key, limit in (('known', 2000), ('missing', 1500)):
        if key in row:
            result[key] = redact_secrets(str(row[key] or ''))[:limit]
    resource = row.get('resource')
    if result['category'] == 'resource' and isinstance(resource, dict):
        urls = {url for r in sources for url in r.get('links', []) if isinstance(url, str)}
        url = resource.get('url', '')
        # Resource existence is distinct from verifying its contents or usefulness.
        if isinstance(url, str) and url in urls and url.startswith(('https://', 'http://')):
            result['resource']['url'] = redact_secrets(url)
        for key in ('name', 'purpose', 'feedback'):
            result['resource'][key] = redact_secrets(str(resource.get(key) or ''))[:1200]
        result['resource']['status'] = 'unverified'
    return result


def save_details(conn, key, item):
    conn.execute('INSERT OR REPLACE INTO item_details VALUES (?,?,?,?,?,?)',
                 (key, category_for(item), item.get('known') or '', item.get('missing') or '',
                  item.get('source_time'), json.dumps(item.get('resource') or {}, ensure_ascii=False)))


def decorate_item(conn, item):
    result = dict(item)
    details = conn.execute('SELECT * FROM item_details WHERE item_key=?', (result['key'],)).fetchone()
    if details:
        result.update(category=details['category'], known=details['known_text'], missing=details['missing_text'],
                      source_time=details['source_time'], resource=json.loads(details['resource_json']))
    else:
        result.update(category=category_for(result), known='', missing='', source_time=None, resource={})
    return result

"""Group-local subject types, kept separate from factual outcome and glossary."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import re
import sqlite3
import uuid

from .content_utils import redact_secrets
from .knowledge_subjects import ALIASES, aliases_for, canonical_subject, prepare_subjects, subjects_for, _mentions, _normalized


USAGE_TAGS = {'armor_tool': '破甲工具', 'reverse_tool': '逆向分析工具',
              'coding_client': '编程客户端', 'model_service': '模型服务',
              'api_gateway': '接口中转', 'account_tool': '账号辅助工具'}
PURPOSE_WORDS = {'armor_tool': ('破甲', '越狱提示词'), 'reverse_tool': ('逆向工具', '逆向分析', '反编译', '进行逆向'),
                 'coding_client': ('编程客户端', '编程助手'), 'model_service': ('模型服务', '大模型服务'),
                 'api_gateway': ('接口中转', 'api中转'), 'account_tool': ('账号辅助', '注册工具')}
SYSTEM = '''organization.usage_tags为最多6项{subject,tag,evidence:[{message_id,quote}]}：
tag只能为armor_tool（破甲工具）、reverse_tool（逆向分析工具）、coding_client（编程客户端）、model_service（模型服务）、api_gateway（接口中转）、account_tool（账号辅助工具）。
标签说明对象是什么/用来做什么，与情形分类、知识/术语、解决状态分别存储。每项须有本条证据中的精确引文，原句同时提到该对象和用途；否定该用途的句子不能支持标签。
subject_catalog是本群已人工确认的对象用途与别名，可用于识别已有对象；只有本条证据真的提到该名称或已确认别名时，才关联目录对象。目录定义不是当前事件的成功、效果、安全性或因果证据。
不得把相邻话题、英文与中文的相似拼写当成别名证明；DSh、Infinite Gen、IG5、无限各代的等同关系需单独证据。只有用途暗示时不要强行确定对象类型。'''


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS subject_usage (
        scope TEXT NOT NULL, subject TEXT NOT NULL, tag TEXT NOT NULL,
        annotation_json TEXT NOT NULL, PRIMARY KEY(scope,subject,tag))''')


def read_catalog(conn, scope=None):
    try:
        query = 'SELECT annotation_json FROM subject_usage'
        args = ()
        if scope is not None:
            query += ' WHERE scope=?'
            args = (scope,)
        return [json.loads(row[0]) for row in conn.execute(query + ' ORDER BY scope,subject,tag', args)]
    except sqlite3.OperationalError as exc:
        if 'no such table: subject_usage' not in str(exc):
            raise
        return []


def scope_catalog(catalog, scope):
    return [entry for entry in catalog if entry.get('scope') == scope]


def _supports_purpose(quote, subject, tag, catalog):
    text = _normalized(quote)
    if any(word in text for word in ('不是', '并非', '不属于', '不能', '不做', 'not a', 'is not',
                                    '另一个', '另一款', '其他工具', '?', '？', '是否', '是不是', '吗', '可能', '也许', '好像',
                                    '没有', '没用', '未用', '未使用', '从未', '并未', '假设', '假如', '如果',
                                    '猜测', '猜想', '不确定', '不知道', '或许', '据说', '听说', '似乎', '不要', '别用')):
        return False
    # A keyword elsewhere in the same message is not a predicate about this
    # subject. Accept explicit type/purpose or an explicitly named tool used
    # for the operation; an unsuccessful operation still need not be a success.
    purpose = '(?:' + '|'.join(re.escape(_normalized(word)) for word in PURPOSE_WORDS[tag]) + ')'
    for alias in aliases_for(subject, catalog):
        name = re.escape(_normalized(alias))
        definition = name + r'[\s：:,，]*(?:是(?:一(?:个|款))?|属于|用于|用来|可(?:以)?用于|开源的?)[\s的]*(?:ai)?' + purpose
        operation = r'(?:使用|通过|用|拿)' + name + r'[\s]*(?:来|进行|做)?' + purpose
        if re.search(definition, text) or re.search(operation, text):
            return True
    return False


def prepare_usage(raw, item, records, catalog=()):
    if not isinstance(raw, list):
        return []
    result = []
    for candidate in raw[:12]:
        if not isinstance(candidate, dict) or candidate.get('tag') not in USAGE_TAGS:
            continue
        subject = candidate.get('subject')
        if not isinstance(subject, str):
            continue
        labels = prepare_subjects([{'name': subject, 'evidence': candidate.get('evidence')}], item, records, catalog)
        if not labels:
            continue
        tag = candidate['tag']
        quotes = []
        for row in labels[0]['evidence']:
            sources = []
            for record in records:
                if record.get('id') == row['message_id']:
                    sources.append(str(record.get('text') or ''))
                    sources.extend(str(file['preview'].get('text') or '') for file in record.get('files', [])
                                   if isinstance(file, dict) and isinstance(file.get('preview'), dict))
                if record.get('quoted_id') == row['message_id']:
                    sources.append(str(record.get('quoted_text') or ''))
            if (_supports_purpose(row['quote'], labels[0]['name'], tag, catalog)
                    and any(row['quote'] in source and _supports_purpose(source, labels[0]['name'], tag, catalog) for source in sources)):
                quotes.append(row)
        if quotes:
            value = {'subject': labels[0]['name'], 'tag': tag, 'origin': 'source', 'evidence': quotes}
            if not any((entry['subject'], entry['tag']) == (value['subject'], tag) for entry in result):
                result.append(value)
    return result[:6]


def usage_for(row, catalog=()):
    scoped = scope_catalog(catalog, row.get('scope'))
    names = subjects_for(row, scoped)
    org = row.get('organization') if isinstance(row.get('organization'), dict) else {}
    result = []
    for entry in scoped:
        if entry['subject'] in names and entry['tag'] in USAGE_TAGS:
            result.append(entry)
    for entry in org.get('usage_tags', []) if isinstance(org.get('usage_tags'), list) else []:
        if isinstance(entry, dict) and entry.get('tag') in USAGE_TAGS and entry.get('evidence'):
            clean = {**entry, 'subject': canonical_subject(entry.get('subject'), scoped), 'origin': 'source'}
            if clean['subject'] in names and not any((r['subject'], r['tag']) == (clean['subject'], clean['tag']) for r in result):
                result.append(clean)
    return result


def usage_markup(entries):
    safe = lambda value: escape(redact_secrets(str(value)), quote=True)
    if not entries:
        return ''
    badges = ''.join('<span class="usage-tag">' + safe(entry['subject']) + ' · ' + USAGE_TAGS[entry['tag']]
                     + ' <small>' + ('人工确认' if entry.get('origin') == 'user' else '原文支持') + '</small></span>' for entry in entries)
    notes = []
    for entry in entries:
        refs = '、'.join('#' + str(q['message_id']) + '：' + safe(q['quote']) for q in entry.get('evidence', []))
        notes.append('<p>' + safe(entry['subject']) + '：' + USAGE_TAGS[entry['tag']] + '。'
                     + safe(entry.get('note') or '') + ('<br>历史依据：' + refs if refs else '') + '</p>')
    return '<div class="usage-tags">' + badges + '</div><details class="usage-basis"><summary>用途标签依据</summary>' + ''.join(notes) + '<p>用途分类不代表本次使用成功或效果已验证。</p></details>'


def set_subject_tag(data_dir, scope, subject, tag, *, aliases=(), note='', evidence=()):
    """Explicit manual classification, with optional exact group-local sources."""
    from .knowledge_config import group_scope
    from .knowledge_store import KnowledgeDB, read_records
    scope = group_scope(scope)
    subject = canonical_subject(redact_secrets(str(subject).strip()))
    aliases = list(dict.fromkeys(redact_secrets(str(alias).strip()) for alias in aliases))
    if not subject or len(subject) > 64 or tag not in USAGE_TAGS or len(aliases) > 24 or any(not a or len(a) > 64 for a in aliases):
        raise ValueError('对象、用途标签或别名无效')
    for alias in [subject, *aliases]:
        known = canonical_subject(alias)
        if (known in ALIASES or known != alias) and known != canonical_subject(subject):
            raise ValueError('别名与已有规范对象冲突')
    quotes = []
    for entry in evidence:
        mid, quote = entry.get('message_id'), entry.get('quote')
        if type(mid) is not int or not isinstance(quote, str) or not quote.strip():
            raise ValueError('历史依据无效')
        records = read_records(data_dir / 'bot.db', scope, after_id=mid-1, before_id=mid, limit=1)
        if not records or quote not in records[0]['text']:
            raise ValueError('历史依据不属于本群原文')
        quotes.append({'message_id': mid, 'quote': redact_secrets(quote)[:500]})
    db = KnowledgeDB(data_dir / 'knowledge.db')
    backup = data_dir / 'backups' / ('knowledge-before-usage-' + uuid.uuid4().hex + '.db')
    backup.parent.mkdir(parents=True, exist_ok=True)
    # Backup before taking the writer lock; backing up this same connection
    # inside a write transaction can wait on its own uncommitted changes.
    with sqlite3.connect(db.path) as before, sqlite3.connect(backup) as target:
        before.backup(target)
    with db.conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = read_catalog(conn, scope)
        for entry in existing:
            if entry['subject'] != subject and {_normalized(a) for a in [subject, *aliases]} & {
                    _normalized(a) for a in [entry['subject'], *entry.get('aliases', [])]}:
                raise ValueError('别名已属于本群其他对象')
        value = {'scope': scope, 'subject': subject, 'tag': tag, 'aliases': aliases, 'origin': 'user',
                 'note': redact_secrets(note)[:1000], 'evidence': quotes,
                 'updated_at': datetime.now(timezone.utc).isoformat()}
        conn.execute('INSERT OR REPLACE INTO subject_usage VALUES (?,?,?,?)',
                     (scope, subject, tag, json.dumps(value, ensure_ascii=False)))
    updated = refresh_catalog_subjects(data_dir, scope)
    return {'status': 'completed', 'subject': subject, 'tag': USAGE_TAGS[tag], 'updated_items': updated, 'backup': str(backup)}


def refresh_catalog_subjects(data_dir, scope):
    """Add source-mentioned catalog subjects; no body, event, cursor or term edits."""
    from .knowledge_store import KnowledgeDB, read_records
    db = KnowledgeDB(data_dir / 'knowledge.db')
    with db.conn() as conn:
        catalog = read_catalog(conn, scope)
        rows = [dict(row) for row in conn.execute('SELECT i.key,i.evidence_json,o.organization_json FROM items i '
                'LEFT JOIN item_organization o ON o.item_key=i.key WHERE i.scope=?', (scope,))]
    changed = []
    for row in rows:
        ids = json.loads(row['evidence_json'])
        records = [record for mid in ids for record in read_records(data_dir / 'bot.db', scope,
                   after_id=mid-1, before_id=mid, limit=1)]
        org = json.loads(row['organization_json'] or '{}')
        labels = []
        for label in org.get('subjects') or []:
            name = canonical_subject(label.get('name'), catalog)
            if name in {entry['subject'] for entry in catalog}:
                labels.extend(prepare_subjects([label], {'evidence_ids': ids}, records, catalog))
            else:
                labels.append(label)
        for entry in catalog:
            matches = [{'message_id': record['id'], 'quote': record['text'][max(0, index-30):index+len(alias)+50]}
                       for record in records for alias in aliases_for(entry['subject'], catalog)
                       if _mentions(record['text'], alias)
                       for index in [record['text'].casefold().find(alias.casefold())] if index >= 0]
            prepared = prepare_subjects([{'name': entry['subject'], 'evidence': matches}], {'evidence_ids': ids}, records, catalog)
            if prepared and not any(canonical_subject(label['name'], catalog) == entry['subject'] for label in labels):
                labels.extend(prepared)
        if labels != org.get('subjects', []):
            org['subjects'] = labels
            changed.append((row, org))
    updated = 0
    with db.conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if read_catalog(conn, scope) != catalog:
            return 0
        for row, org in changed:
            current = conn.execute('SELECT organization_json FROM item_organization WHERE item_key=?', (row['key'],)).fetchone()
            if (current[0] if current else None) != row['organization_json']:
                continue
            current_item = conn.execute('SELECT evidence_json FROM items WHERE key=? AND scope=?', (row['key'], scope)).fetchone()
            if not current_item or current_item[0] != row['evidence_json']:
                continue
            conn.execute('INSERT OR REPLACE INTO item_organization VALUES (?,?)', (row['key'], json.dumps(org, ensure_ascii=False)))
            updated += 1
    return updated

"""Source-grounded topics, referents and lifecycle annotations, separate from facts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .content_utils import redact_secrets


TOPICS = {'ai_reverse': '逆向与工具', 'model_usage': '模型使用与接入',
          'billing': '额度计费与订阅', 'development': '编程开发与部署',
          'accounts': '账号登录与风控', 'resources': '资料与工具资源',
          'service_status': '服务状态与公告', 'other': '其他／待分类'}

SYSTEM = '''
每个item增加organization对象：topics为下列1至3个主题ID：ai_reverse/model_usage/billing/development/accounts/resources/service_status/other；retention_class为brief或detailed；progress_kind为new_information/repeat/unknown；progress_evidence为{message_id,quote}或null。
主题用于资料分类，与knowledge/question/resource/transient资料类型独立。简短且缺少细节的求助为brief，有环境、错误、操作或有效反馈的问题为detailed。
progress_kind必须比较已有同一讨论：新条件、排查步骤、结果或有效资源线索可为new_information，但须用当前批次原文的连续精确引文支持；重复提问和改写不得算新进展。无法判断用unknown。
organization.subject为{name,ambiguous,evidence:[{message_id,quote}]}。正文必须独立说明所用工具/服务、操作对象与反馈；避免“用在GPT上”“这个封了”等指代不明的结论。对象可确认时给出原文支持的名称和精确引文；缺少引用或只能从相邻聊天猜测时ambiguous=true、name为空，并在missing说明缺失信息。
“我的已经封了”不证明被封的是哪个平台账号，也不证明某工具导致封禁；人物自述、相邻话题和因果关系必须分开。无法确认时标题和正文明确“对象待确认”，不要补造工具名或账号类型。
organization.subjects用于按主题浏览，按主要对象优先列出最多3项{name,evidence:[{message_id,quote}]}。例如智谱（含GLM）、WorkBuddy、OpenCode；其他产品或技术也可成为主题。每项引文必须逐字来自本条证据消息且明确提及对象，不能只凭“封号、额度”等情形猜产品。subjects仅归类，不改变subject的指代确认、验证状态或话题关联；同主题的不同账号、版本、成员经历仍分别记录。
'''.strip()


def ensure_schema(conn):
    from .knowledge_usage import ensure_schema as usage_schema
    usage_schema(conn)
    conn.execute('CREATE TABLE IF NOT EXISTS item_organization (item_key TEXT PRIMARY KEY, organization_json TEXT NOT NULL)')
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_archives (
        scope TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL,
        state TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(scope,record_type,record_id))''')


def _quote(value, item, records, *, current=False):
    if not isinstance(value, dict):
        return None
    mid, text = value.get('message_id'), value.get('quote')
    if type(mid) is not int or mid not in item.get('evidence_ids', []) or not isinstance(text, str) or not text.strip():
        return None
    for row in records:
        direct = row.get('id') == mid and (not current or not row.get('context_only'))
        quoted = not current and row.get('quoted_id') == mid
        source = row.get('text') if direct else row.get('quoted_text') if quoted else None
        sources = [source]
        if direct:
            sources.extend(file['preview'].get('text') for file in row.get('files', [])
                           if isinstance(file, dict) and isinstance(file.get('preview'), dict))
        if any(isinstance(source, str) and text.strip() in source for source in sources):
            return {'message_id': mid, 'quote': redact_secrets(text.strip())[:1500]}
    return None


def prepare_organization(item, records, subject_catalog=()):
    raw = item.get('organization')
    raw = raw if isinstance(raw, dict) else {}
    legacy = not raw or raw.get('legacy_unassessed') is True
    topics = raw.get('topics')
    topics = list(dict.fromkeys(t for t in topics if isinstance(t, str) and t in TOPICS))[:3] if isinstance(topics, list) else []
    progress = raw.get('progress_kind')
    quote = _quote(raw.get('progress_evidence'), item, records, current=True)
    if progress not in ('new_information', 'repeat', 'unknown') or (progress == 'new_information' and quote is None):
        progress = 'unknown'
    source_times = {}
    for record in records:
        if record.get('id') not in item.get('evidence_ids', []) or record.get('context_only'):
            continue
        try:
            stamp = datetime.fromisoformat(str(record.get('time') or '').replace('Z', '+00:00'))
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                source_times[record['id']] = stamp.astimezone(timezone.utc)
        except ValueError:
            pass
    progress_time = source_times.get(quote['message_id']) if quote and progress == 'new_information' else None
    subject = raw.get('subject')
    subject = subject if isinstance(subject, dict) else {}
    evidence = [_quote(row, item, records) for row in subject.get('evidence', [])[:8]] if isinstance(subject.get('evidence'), list) else []
    evidence = [row for row in evidence if row]
    raw_name = subject.get('name')
    name = redact_secrets(raw_name.strip())[:300] if isinstance(raw_name, str) else ''
    if not name or not any(name in row['quote'] for row in evidence):
        name = ''
    from .knowledge_subjects import prepare_subjects, add_background_subjects
    from .knowledge_usage import prepare_usage
    from .knowledge_tags import prepare_topic_tags
    from .knowledge_background import background_fingerprint
    from .knowledge_tags import VERSION as TAGS_VERSION
    tags = prepare_topic_tags(raw.get('topic_tags'), item, records)
    subjects = add_background_subjects(prepare_subjects(raw.get('subjects'), item, records, subject_catalog), item, records, subject_catalog)
    return {'topics': topics or ['other'], 'legacy_unassessed': legacy,
            'subjects': subjects,
            'usage_tags': prepare_usage(raw.get('usage_tags'), item, records, subject_catalog),
            'topic_tags': tags,
            'tags_version': TAGS_VERSION if isinstance(raw.get('topic_tags'), list) else 0,
            'tags_complete': isinstance(raw.get('topic_tags'), list) and bool(tags or subjects),
            'background_fingerprint': background_fingerprint() if isinstance(raw.get('topic_tags'), list) else '',
            'subjects_version': 1 if isinstance(raw.get('subjects'), list) else 0,
            'subjects_complete': isinstance(raw.get('subjects'), list),
            'retention_class': 'brief' if raw.get('retention_class') == 'brief' else 'detailed',
            'progress_kind': progress, 'progress_evidence': quote if progress == 'new_information' else None,
            'progress_time': progress_time.isoformat() if progress_time else None,
            'first_source_time': min(source_times.values()).isoformat() if source_times else None,
            'subject': {'name': name, 'ambiguous': subject.get('ambiguous') is True or (not legacy and not name),
                        'evidence': evidence}}


def save_organization(conn, key, item):
    organization = item.get('organization')
    if isinstance(organization, dict):
        conn.execute('INSERT OR REPLACE INTO item_organization VALUES (?,?)',
                     (key, json.dumps(organization, ensure_ascii=False)))


def decorate_organization(conn, item):
    result = dict(item)
    try:
        row = conn.execute('SELECT organization_json FROM item_organization WHERE item_key=?', (item.get('key'),)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table: item_organization' not in str(exc):
            raise
        row = None
    if row:
        result['organization'] = json.loads(row[0])
    return result


def archive_overrides(conn):
    try:
        return {(row['scope'], row['record_type'], row['record_id']): dict(row)
                for row in conn.execute('SELECT * FROM knowledge_archives')}
    except sqlite3.OperationalError as exc:
        if 'no such table: knowledge_archives' not in str(exc):
            raise
        return {}


def set_archive(db, scope, record_type, record_id, state, *, reason=''):
    from datetime import datetime, timezone
    if record_type not in ('topic', 'item') or state not in ('archived', 'active', 'auto'):
        raise ValueError('归档对象或状态无效')
    with db.conn() as conn:
        table, column = ('knowledge_threads', 'id') if record_type == 'topic' else ('items', 'key')
        if not conn.execute(f'SELECT 1 FROM {table} WHERE scope=? AND {column}=?', (scope, record_id)).fetchone():
            raise ValueError('归档对象不属于本群或不存在')
        if record_type == 'item' and state != 'auto':
            tracked = conn.execute('SELECT thread_id FROM knowledge_thread_events WHERE scope=? AND item_key=? LIMIT 1',
                                   (scope, record_id)).fetchone()
            if tracked:
                raise ValueError('该条目属于讨论，请对完整话题设置归档状态：--topic-id ' + tracked[0])
        if state == 'auto':
            conn.execute('DELETE FROM knowledge_archives WHERE scope=? AND record_type=? AND record_id=?', (scope, record_type, record_id))
        else:
            conn.execute('INSERT OR REPLACE INTO knowledge_archives VALUES (?,?,?,?,?,?)',
                (scope, record_type, record_id, state, redact_secrets(reason)[:1000], datetime.now(timezone.utc).isoformat()))
    return {'status': 'completed', 'state': state, 'record_id': record_id}

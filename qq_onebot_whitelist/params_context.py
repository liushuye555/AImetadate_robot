"""Bind parameter evidence to its source image; keep unresolved material out of reports."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from .content_utils import redact_secrets
from .prompt_binding import is_params_message
from .store import reply_to_message_id

VERSION = 1
NEIGHBOR_LIMIT = 256  # Busy groups need more than a dozen messages for a three-minute reply.
DETAIL = re.compile(r'\b(?:int[48]|fp(?:8|16|32)|bf16)\b', re.I)
QUESTION = re.compile(r'[?？]|怎么|什么|哪个|哪种|多少|为何|为什么|(?:吗|呢)[。！!~]?$')
SPECULATION = re.compile(r'可能|也许|估计|我猜|了吧|是吧|污染了吧')
FACT = re.compile(r'\d|用|改|调|训练|去掉|降低|增加|建议|效果|恢复|快|慢|加不加|不需要|成功|失败', re.I)
PROGRESS = re.compile(r'正在(?:思考|处理|重新连接)|请稍候|待生成|开始生成|重新连接\s*\d/\d|已处理\s*\d')


def _params(text):
    return is_params_message(text) or bool(DETAIL.search(text))


def substantive(text):
    text = (text or '').strip()
    if not _params(text) or len(text) < 6 or PROGRESS.search(text):
        return False
    if QUESTION.search(text) and not re.search(r'(?:cfg|seed|steps|采样器|步数)\s*[:：=]\s*\S+', text, re.I):
        return False
    if SPECULATION.search(text) and not re.search(r'实测|验证|复现|调整后', text):
        return False
    return bool(FACT.search(text))


def _event(raw):
    try:
        value=json.loads(raw or '{}')
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):
        return {}


def _record(row):
    mid, key, actor, text, seen, raw=row
    event=_event(raw)
    try:
        if event.get('time') is not None:
            stamp = float(event['time'])
        else:
            observed = datetime.fromisoformat(seen)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            stamp = observed.timestamp()
    except (TypeError, ValueError, OverflowError):
        stamp = None
    segments=event.get('message') or []
    return {'id':mid,'message_key':str(event.get('message_id') or key or ''),'user_id':str(actor or ''),
            'text':str(text or ''),'seen_at':seen,'timestamp':stamp,'reply_to_message_id':reply_to_message_id(event),
            'image_count':sum(s.get('type')=='image' for s in segments if isinstance(s,dict)) if isinstance(segments,list) else 0}


def build_image_context(store, scope: str, message_db_id: int | None, *, window_seconds: int = 180) -> dict:
    empty={'status':'pending','text':'','evidence_ids':[],'reason':'缺少与本图关联的实质参数证据','source_id':message_db_id,'records':[]}
    if type(message_db_id) is not int or message_db_id <= 0:
        return {**empty,'reason':'没有可追溯的原始图片消息'}
    columns='id,message_key,user_id,text,seen_at,raw_json'
    with store._conn() as conn:
        source_row=conn.execute('SELECT '+columns+' FROM messages WHERE scope=? AND id=?',(scope,message_db_id)).fetchone()
        if not source_row:
            return {**empty,'reason':'原始图片消息不存在或不属于本群'}
        before=conn.execute('SELECT '+columns+' FROM messages WHERE scope=? AND id<? ORDER BY id DESC LIMIT ?',(scope,message_db_id,NEIGHBOR_LIMIT)).fetchall()[::-1]
        after=conn.execute('SELECT '+columns+' FROM messages WHERE scope=? AND id>? ORDER BY id LIMIT ?',(scope,message_db_id,NEIGHBOR_LIMIT)).fetchall()
        source=_record(source_row)
        records=[_record(r) for r in [*before,source_row,*after]]
        records=[r for r in records if r['id']==message_db_id or (r['timestamp'] is not None and source['timestamp'] is not None and abs(r['timestamp']-source['timestamp'])<=window_seconds)]
        # The image may explicitly quote an older parameter post outside the time window.
        if source['reply_to_message_id'] and not any(r['message_key']==source['reply_to_message_id'] for r in records):
            quoted=conn.execute('SELECT '+columns+' FROM messages WHERE scope=? AND message_key=? LIMIT 1',(scope,source['reply_to_message_id'])).fetchone()
            if quoted:records.append(_record(quoted))
    records.sort(key=lambda r:r['id'])
    by_key = {r['message_key']: r for r in records if r['message_key']}

    def relevant_question(record):
        if not _params(record['text']) or not QUESTION.search(record['text']):
            return False
        # A question explicitly about another picture is not evidence for this one.
        return not record['reply_to_message_id'] or record['reply_to_message_id'] == source['message_key']

    same_actor=[r for r in records if r['user_id']==source['user_id']]
    previous_image=max((r['id'] for r in same_actor if r['image_count'] and r['id']<message_db_id),default=0)
    next_image=min((r['id'] for r in same_actor if r['image_count'] and r['id']>message_db_id),default=10**30)
    support=[]
    for r in records:
        if not substantive(r['text']):continue
        quoted_question = by_key.get(r['reply_to_message_id'])
        same_actor_reply = (not r['reply_to_message_id']
                            or (quoted_question is not None and relevant_question(quoted_question)))
        linked=(r['id']==message_db_id or r['message_key']==source['reply_to_message_id']
                or (source['message_key'] and r['reply_to_message_id']==source['message_key'])
                or (source['user_id'] and r['user_id']==source['user_id']
                    and previous_image<r['id']<next_image and same_actor_reply))
        if linked:support.append(r)
    if not support:
        return {**empty,'records':records}
    selected={r['id']:r for r in support}
    selected[source['id']]=source
    for answer in support:
        # Keep the nearest actual parameter question, rather than all neighboring chat.
        questions=[r for r in records if r['id']<answer['id'] and relevant_question(r)
                   and answer['timestamp'] is not None and r['timestamp'] is not None and 0<=answer['timestamp']-r['timestamp']<=90]
        if answer['reply_to_message_id']:
            questions = [r for r in questions if r['message_key'] == answer['reply_to_message_id']]
        if questions:
            question=questions[-1];selected[question['id']]=question
    question_keys={r['message_key'] for r in selected.values() if QUESTION.search(r['text'])}
    for r in records:
        if r['reply_to_message_id'] in question_keys and substantive(r['text']):selected[r['id']]=r
    aliases={};lines=[]
    for r in sorted(selected.values(),key=lambda r:r['id']):
        actor=r['user_id']
        if actor not in aliases:aliases[actor]='成员'+str(len(aliases)+1)
        label='原图消息' if r['id']==message_db_id else ('提问' if QUESTION.search(r['text']) else '讨论')
        text=redact_secrets(r['text']).strip()[:700] or '［图片］'
        quote=next((p['id'] for p in records if p['message_key']==r['reply_to_message_id']),None)
        reference=('，引用 #'+str(quote)) if quote else ''
        lines.append(f"#{r['id']} · {r['seen_at']} · {aliases[actor]} · {label}{reference}\n{text}")
    return {'status':'selected','text':'\n\n'.join(lines)[:6000],'evidence_ids':sorted(selected),
            'reason':'有同条、引用或同发送者图片帖内的实质参数讨论','source_id':message_db_id,'records':records}


class _ReadOnlyStore:
    """Audit existing history without creating tables or changing journal settings."""

    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        try:
            yield conn
        finally:
            conn.close()

    def image_discussion(self, image_id):
        with self._conn() as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='image_discussions' AND type='table'").fetchone()
            if not exists:
                return None
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM image_discussions WHERE image_id=?', (image_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['evidence_ids'] = json.loads(result.pop('evidence_json'))
        return result


def audit_params(project_dir: Path, *, apply: bool = False, image_ids: list[int] | None = None) -> dict:
    from .store import Store
    root=Path(project_dir)
    store=Store(root/'data'/'bot.db') if apply else _ReadOnlyStore(root/'data'/'bot.db')
    with store._conn() as conn:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(images)')}
        source_column = 'message_db_id' if 'message_db_id' in columns else 'NULL'
        sql = 'SELECT id,scope,raw_json,' + source_column + ' FROM images WHERE '
        if image_ids is not None:
            if not image_ids:return {'selected':0,'pending':0,'rejected':0,'checked':0}
            if len(image_ids)>1000 or any(type(i) is not int or i<=0 for i in image_ids):raise ValueError('图片编号无效')
            sql+='id IN ('+','.join('?' for _ in image_ids)+')'
        else:
            sql+="(retention_reason='params_discussion' OR context_reason='params_discussion')"
        rows=conn.execute(sql+' ORDER BY id',image_ids or []).fetchall()
    counts={'selected':0,'pending':0,'rejected':0,'checked':0,'manual_preserved':0}
    samples=[]
    for iid,scope,raw_json,canonical_id in rows:
        existing=store.image_discussion(iid)
        if existing and existing['manual']:
            result=existing;counts['manual_preserved']+=1
        else:
            mid=canonical_id or _event(raw_json).get('message_db_id')
            result=build_image_context(store,scope,mid)
            if apply:
                store.set_image_discussion(iid,result['status'],result['reason'],result['text'],result['evidence_ids'],version=VERSION)
                result = store.image_discussion(iid)
        counts[result['status']]+=1;counts['checked']+=1
        samples.append({'id':iid,'status':result['status'],'reason':result['reason'],'evidence_ids':result['evidence_ids']})
    return {**counts,'samples':samples}


def main():
    from .store import Store
    parser=argparse.ArgumentParser(description='参数讨论关联检查与人工纠错；不删除原件')
    parser.add_argument('--project-dir',type=Path,default=Path('.'))
    sub=parser.add_subparsers(dest='action',required=True)
    audit=sub.add_parser('audit');audit.add_argument('--apply',action='store_true');audit.add_argument('--image-id',type=int,action='append')
    feedback=sub.add_parser('feedback');feedback.add_argument('--image-id',type=int,required=True);feedback.add_argument('--status',choices=['selected','rejected','pending'],required=True);feedback.add_argument('--reason',required=True)
    args=parser.parse_args()
    if args.action=='audit':result=audit_params(args.project_dir,apply=args.apply,image_ids=args.image_id)
    else:
        store=Store(args.project_dir/'data'/'bot.db')
        context = {'text': '', 'evidence_ids': []}
        if args.status == 'selected':
            with store._conn() as conn:
                row = conn.execute('SELECT scope,raw_json,message_db_id FROM images WHERE id=?', (args.image_id,)).fetchone()
            if row is None:
                parser.error('图片不存在')
            context = build_image_context(store, row[0], row[2] or _event(row[1]).get('message_db_id'))
            if context['status'] != 'selected':
                parser.error('没有关联的实质讨论，不能直接标为有效；请先补全证据')
        result={'saved':store.set_image_discussion(args.image_id,args.status,args.reason,
                    context_text=context['text'], evidence_ids=context['evidence_ids'], manual=True)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

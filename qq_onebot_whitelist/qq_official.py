"""QQ Open Platform transport. No ordinary-account login or OneBot server required.

Protocol reference: https://bot.q.qq.com/wiki/develop/api-v2/
IDs are namespaced by application; official OpenIDs never masquerade as QQ numbers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import websockets

API_BASE = 'https://api.bot.qq.com'
TOKEN_BASE = 'https://api.bot.qq.com'
INTENTS = 1 << 25
UNSUPPORTED = {'get_group_msg_history', 'get_group_root_files', 'get_group_files_by_folder',
               'get_group_file_url', 'send_forward_msg', 'send_group_forward_msg'}
_sessions: dict[tuple[str, str], dict] = {}


class OfficialError(RuntimeError):
    """Sanitized transport failure: never include request/response bodies or credentials."""


class OfficialFatalError(OfficialError):
    pass


def identity(config, value) -> str:
    prefix = f'qqofficial:{config.official_app_id}:'
    text = str(value or '')
    if text.startswith(prefix):
        return text
    if text.startswith('qqofficial:'):
        raise OfficialError('OpenID 属于其他机器人应用')
    return prefix + text


def raw_id(config, value) -> str:
    prefix = f'qqofficial:{config.official_app_id}:'
    value = str(value or '')
    if not value.startswith(prefix) or not value[len(prefix):]:
        raise OfficialError('请使用当前官方机器人的 OpenID，不能使用旧 QQ 号或群号')
    return value[len(prefix):]


def state_path(config) -> Path:
    root = config.source_path.parent if config.source_path else Path.cwd()
    return root / 'run' / 'qq-official-state.json'


def credential_key(config) -> str:
    return hashlib.sha256((config.official_app_id + '\0' + config.official_app_secret).encode()).hexdigest()


def read_state(config) -> dict:
    try:
        value = json.loads(state_path(config).read_text(encoding='utf-8'))
        return value if value.get('credentialKey') == credential_key(config) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def write_state(config, **changes) -> None:
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    from .manager_owner import process_identity
    state = {**read_state(config), **changes, 'appId': config.official_app_id,
             'credentialKey': credential_key(config), 'pid': os.getpid(),
             'created': process_identity(os.getpid()), 'observedAt': time.time()}
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def status(config) -> dict:
    from .gateway import info
    from .manager_owner import is_process_alive
    state = read_state(config)
    ready = bool(config.official_app_id and config.official_app_secret)
    online = bool(ready and state.get('online') and time.time() - state.get('observedAt', 0) < 60
                  and state.get('created') and is_process_alive(state.get('pid'), state.get('created')))
    return {**info(config), 'gatewayRunning': online, 'onebot': online,
            'qqLoggedIn': online, 'qqStatusKnown': online, 'qqNumber': config.official_app_id,
            'qqNickname': state.get('nickname', 'QQ 官方机器人'), 'credentialsConfigured': ready,
            'gatewayError': ('官方平台已停用或封禁；请检查开放平台后手动重连' if state.get('blocked') else
                             ('' if ready else '尚未绑定 QQ 官方机器人')),
            'allMessagesObserved': bool(state.get('allMessagesObserved'))}


def _segments(config, data: dict, self_id: str, mentioned=False) -> list[dict]:
    segments = []
    text = str(data.get('content') or '')
    # Platform-provided mention event is authoritative even if content has no marker.
    if mentioned:
        segments.append({'type': 'at', 'data': {'qq': self_id}})
    cursor = 0
    for match in re.finditer(r'<@!?([^>]+)>', text):
        if match.start() > cursor:
            segments.append({'type': 'text', 'data': {'text': text[cursor:match.start()]}})
        value = match[1]
        segments.append({'type': 'at', 'data': {'qq': 'all' if value == 'all' else identity(config, value)}})
        cursor = match.end()
    if cursor < len(text):
        segments.append({'type': 'text', 'data': {'text': text[cursor:]}})
    for index, item in enumerate(data.get('attachments') or []):
        if not isinstance(item, dict) or not item.get('url'):
            continue
        kind = str(item.get('content_type') or '')
        url = str(item['url'])
        if kind.startswith('image/'):
            segments.append({'type': 'image', 'data': {'url': url, 'file': url}})
        else:
            attachment_id = hashlib.sha256((str(data.get('id') or '') + ':' + str(index) + ':' + str(item.get('filename') or url)).encode()).hexdigest()
            segments.append({'type': 'file', 'data': {'url': url, 'file_id': 'official-' + attachment_id, 'name': item.get('filename') or '附件',
                                                      'size': item.get('size')}})
    # Structured share-card links participate in normal link collection.
    link = ((data.get('ark_data') or {}).get('fields') or {}).get('jump_url')
    if link:
        segments.append({'type': 'text', 'data': {'text': '\n' + str(link)}})
    # Quoted content belongs to the original author, never the new sender.
    if data.get('message_type') == 102 and data.get('msg_elements'):
        segments.append({'type': 'forward', 'data': {'id': identity(config, 'forward-' + str(data.get('id') or ''))}})
    return segments


def convert_event(config, event_type: str, data: dict, bot_id='') -> dict | None:
    if event_type not in ('GROUP_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE', 'C2C_MESSAGE_CREATE'):
        return None
    group = event_type.startswith('GROUP_')
    author = data.get('author') or {}
    uid = author.get('member_openid' if group else 'user_openid') or author.get('id')
    if not uid or not data.get('id') or (group and not data.get('group_openid')):
        return None
    self_id = identity(config, bot_id or config.official_app_id)
    try:
        stamp = int(datetime.fromisoformat(str(data.get('timestamp')).replace('Z', '+00:00')).timestamp())
    except (ValueError, TypeError):
        stamp = int(time.time())
    refs = dict(item.split('=', 1) for item in (data.get('message_scene') or {}).get('ext', [])
                if isinstance(item, str) and '=' in item)
    message = _segments(config, data, self_id, event_type == 'GROUP_AT_MESSAGE_CREATE')
    if not refs.get('ref_msg_idx') and data.get('message_type') == 103:
        quoted = data.get('msg_elements') or []
        if quoted and isinstance(quoted[0], dict) and quoted[0].get('msg_idx'):
            refs['ref_msg_idx'] = str(quoted[0]['msg_idx'])
    if refs.get('ref_msg_idx'):
        message.insert(0, {'type': 'reply', 'data': {'id': refs['ref_msg_idx']}})
    nodes = []
    if data.get('message_type') == 102:
        for node in data.get('msg_elements') or []:
            if not isinstance(node, dict):
                continue
            original = node.get('author') or {}
            nodes.append({'user_id': identity(config, original.get('member_openid') or original.get('id') or 'unknown'),
                          'nickname': original.get('username') or '未知发送者',
                          'message': _segments(config, node, self_id)})
    return {'post_type': 'message', 'message_type': 'group' if group else 'private',
            'message_id': str(data['id']), 'user_id': identity(config, uid), 'self_id': self_id,
            **({'group_id': identity(config, data['group_openid'])} if group else {}),
            'sender': {'user_id': identity(config, uid), 'nickname': author.get('username') or '',
                       'role': author.get('member_role') or 'member'},
            'time': stamp, 'message': message, 'real_id': refs.get('msg_idx'),
            'source': 'qq_official', 'official_event_type': event_type,
            'official_forward_nodes': nodes}


def _http_json(base: str, method: str, path: str, body=None, token='', timeout=15):
    headers = {'Content-Type': 'application/json', 'User-Agent': 'qq-onebot-whitelist/qq-official'}
    if token:
        headers['Authorization'] = 'QQBot ' + token
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(16 * 1024 * 1024))
    except HTTPError as exc:
        raise OfficialError(f'QQ 官方接口 HTTP {exc.code}') from None
    except (URLError, OSError, ValueError):
        raise OfficialError('QQ 官方接口连接或响应异常') from None
    if not isinstance(data, dict) or data.get('code') not in (None, 0):
        raise OfficialError('QQ 官方接口拒绝请求；请检查权限和频控')
    return data


class OfficialConnection:
    def __init__(self, config, *, events=False, open_timeout=15):
        self.config, self.events, self.open_timeout = config, events, open_timeout
        self._gateway_disabled_actions = config.onebot_disabled_actions | UNSUPPORTED
        self.ws = None
        self.tasks = []
        self.available = asyncio.Event()
        self.done = False
        self._inbox_local = threading.local()
        self.all_messages_observed = bool(read_state(config).get('allMessagesObserved'))
        self.ready = asyncio.Event()
        self.failure = None
        self.token = ''
        self.expires_at = 0
        self.bot_id = read_state(config).get('botId') or config.official_app_id
        self.seq = None
        self.ack = True
        self.key = (str(config.source_path), config.official_app_id)
        self.api_base, self.token_base = API_BASE, TOKEN_BASE

    async def request(self, method, path, body=None, *, authenticated=True):
        if isinstance(self.failure, OfficialFatalError) or read_state(self.config).get('blocked'):
            raise OfficialFatalError('官方通道已停止，请检查平台状态后手动重连')
        token = await self.access_token() if authenticated else ''
        return await asyncio.to_thread(_http_json, self.api_base, method, path, body, token)

    async def access_token(self):
        if self.token and time.monotonic() < self.expires_at:
            return self.token
        data = await asyncio.to_thread(_http_json, self.token_base, 'POST', '/app/getAppAccessToken',
                                     {'appId': self.config.official_app_id,
                                      'clientSecret': self.config.official_app_secret})
        if not data.get('access_token'):
            raise OfficialError('QQ 官方机器人鉴权失败')
        self.token = str(data['access_token'])
        duration = max(1, int(data.get('expires_in') or 7200))
        self.expires_at = time.monotonic() + max(1, duration - min(300, duration / 3))
        return self.token

    async def __aenter__(self):
        if not self.config.official_app_id or not self.config.official_app_secret:
            raise OfficialError('尚未绑定 QQ 官方机器人；请在设置中填写 AppID 和 AppSecret')
        if read_state(self.config).get('blocked'):
            raise OfficialFatalError('官方平台已停用或封禁；请检查后手动重连')
        if not self.events:
            return self
        try:
            result = await self.request('GET', '/gateway')
            url = str(result.get('url') or '')
            if not url.startswith('wss://'):
                raise OfficialError('官方网关未返回安全的 WebSocket 地址')
            self.ws = await websockets.connect(url, open_timeout=self.open_timeout,
                                               max_size=self.config.onebot_max_message_mb * 1024 * 1024)
            self.tasks.append(asyncio.create_task(self._pump()))
            await asyncio.wait_for(self.ready.wait(), self.open_timeout)
            if self.failure:
                raise self.failure
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.ws is not None:
            await self.ws.close()
        if self.events:
            write_state(self.config, online=False)

    def inbox(self, operation, event=None):
        """Persist before advancing RESUME; consumer latency never fills an ACK queue."""
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        conn = getattr(self._inbox_local, 'connection', None)
        if conn is None:
            conn = sqlite3.connect(self.config.data_dir / 'bot.db', timeout=15)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS official_inbox ('
                         'app_id TEXT, message_id TEXT, event_json TEXT, state TEXT DEFAULT \'pending\','
                         'created_at REAL, PRIMARY KEY(app_id,message_id))')
            conn.execute('CREATE INDEX IF NOT EXISTS official_inbox_pending ON official_inbox(app_id,state,created_at)')
            conn.commit()
            self._inbox_local.connection = conn
        with conn:
            if operation == 'put':
                conn.execute('INSERT OR IGNORE INTO official_inbox(app_id,message_id,event_json,created_at) VALUES (?,?,?,?)',
                             (self.config.official_app_id, event['message_id'], json.dumps(event, ensure_ascii=False), time.time()))
            elif operation == 'next':
                row = conn.execute('SELECT event_json FROM official_inbox WHERE app_id=? AND state=\'pending\' ORDER BY created_at,rowid LIMIT 1',
                                   (self.config.official_app_id,)).fetchone()
                return json.loads(row[0]) if row else None
            elif operation in ('processed', 'failed'):
                conn.execute('UPDATE official_inbox SET state=? WHERE app_id=? AND message_id=?',
                             (operation, self.config.official_app_id, event['message_id']))
            conn.commit()

    async def acknowledge(self, event, *, failed=False):
        await asyncio.to_thread(self.inbox, 'failed' if failed else 'processed', event)

    async def _heartbeat(self, interval):
        while True:
            await asyncio.sleep(interval)
            if not self.ack:
                await self.ws.close()
                return
            self.ack = False
            await self.ws.send(json.dumps({'op': 1, 'd': self.seq}))

    async def _pump(self):
        try:
            async for raw in self.ws:
                packet = json.loads(raw)
                op, data = packet.get('op'), packet.get('d') or {}
                if op == 10:
                    token = await self.access_token()
                    saved = _sessions.get(self.key)
                    auth = {'token': 'QQBot ' + token}
                    auth.update(saved if saved else {'intents': INTENTS, 'shard': [0, 1]})
                    await self.ws.send(json.dumps({'op': 6 if saved else 2, 'd': auth}))
                    interval = max(.1, float(data['heartbeat_interval']) / 1000)
                    self.tasks.append(asyncio.create_task(self._heartbeat(interval)))
                elif op == 11:
                    self.ack = True
                    if self.ready.is_set():
                        write_state(self.config, online=True)
                elif op in (7, 9):
                    if op == 9:
                        _sessions.pop(self.key, None)
                    raise OfficialError('官方网关要求重新连接')
                elif op == 0:
                    event_type = packet.get('t')
                    if event_type in ('READY', 'RESUMED'):
                        if event_type == 'READY':
                            _sessions[self.key] = {'session_id': data['session_id'], 'seq': packet.get('s')}
                            self.bot_id = str((data.get('user') or {}).get('id') or self.bot_id)
                        write_state(self.config, online=True, blocked=False,
                                    botId=self.bot_id,
                                    nickname=(data.get('user') or {}).get('username') or 'QQ 官方机器人')
                        self.ready.set()
                    event = convert_event(self.config, str(event_type), data, self.bot_id)
                    if event:
                        if event_type == 'GROUP_MESSAGE_CREATE' and not self.all_messages_observed:
                            write_state(self.config, online=True, allMessagesObserved=True)
                            self.all_messages_observed = True
                        await asyncio.to_thread(self.inbox, 'put', event)
                        self.available.set()
                # Every preceding message is now durably committed. Reconnect can safely resume here.
                if packet.get('s') is not None:
                    self.seq = packet['s']
                    if self.key in _sessions:
                        _sessions[self.key]['seq'] = self.seq
        except Exception as exc:
            code = getattr(getattr(exc, 'rcvd', None), 'code', None)
            if code in (4914, 4915):
                write_state(self.config, online=False, blocked=True, closeCode=code)
                self.failure = OfficialFatalError('QQ 官方平台已停用或封禁机器人，请检查开放平台')
            else:
                if code in (4004, 4006, 4007, 4009):
                    _sessions.pop(self.key, None)
                self.failure = exc if isinstance(exc, OfficialError) else OfficialError('QQ 官方网关连接中断')
        finally:
            if not self.ready.is_set() and self.failure is None:
                self.failure = OfficialError('QQ 官方网关未完成就绪握手')
            self.ready.set()
            self.done = True
            self.available.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if isinstance(self.failure, OfficialFatalError):
                raise self.failure
            self.available.clear()
            event = await asyncio.to_thread(self.inbox, 'next')
            if event is not None:
                return json.dumps(event, ensure_ascii=False)
            if self.done:
                if self.failure:
                    raise self.failure
                raise StopAsyncIteration
            await self.available.wait()

    async def send(self, packet):
        data = json.loads(packet)
        await self.execute(data['action'], data.get('params') or {})

    async def execute(self, action, params):
        from .gateway import UnsupportedActionError
        if isinstance(self.failure, OfficialFatalError) or read_state(self.config).get('blocked'):
            raise OfficialFatalError('官方通道已停止，请检查平台状态后手动重连')
        if action in self._gateway_disabled_actions:
            raise UnsupportedActionError(action, 'unsupported')
        if action in ('send_group_msg', 'send_private_msg'):
            group = action == 'send_group_msg'
            peer = raw_id(self.config, params.get('group_id' if group else 'user_id'))
            message = params.get('message')
            path = f'/v2/{"groups" if group else "users"}/{quote(peer, safe="")}'
            parts = [('text', message)] if isinstance(message, str) else []
            if isinstance(message, list):
                for segment in message:
                    item = segment.get('data') or {}
                    if segment.get('type') == 'text' and item.get('text'):
                        parts.append(('text', str(item['text'])))
                    elif segment.get('type') == 'image':
                        url = str(item.get('url') or item.get('file') or '')
                        if not url.startswith(('https://', 'http://')):
                            raise UnsupportedActionError(action, 'remote_image_url_required')
                        parts.append(('image', url))
                    elif segment.get('type') not in ('reply', 'at', 'face'):
                        raise UnsupportedActionError(action, 'unsupported_segment')
            if not parts:
                raise OfficialError('没有可发送的官方消息内容')
            data = {}
            for index, (kind, content) in enumerate(parts):
                sequence = int(hashlib.sha256((str(params.get('msg_id') or time.time_ns()) + ':' + str(index) + ':' + content).encode()).hexdigest()[:8], 16) % 65535 + 1
                body = {'msg_seq': sequence}
                if params.get('msg_id'):
                    body['msg_id'] = params['msg_id']
                if kind == 'text':
                    body.update(msg_type=0, content=content)
                else:
                    media = await self.request('POST', path + '/files', {'file_type': 1, 'url': content, 'srv_send_msg': False})
                    if not media.get('file_info'):
                        raise OfficialError('官方图片上传未返回有效凭据')
                    body.update(msg_type=7, media={'file_info': media['file_info']})
                data = await self.request('POST', path + '/messages', body)
                if not data.get('id'):
                    raise OfficialError('官方平台未确认消息发送结果')
            return {'status': 'ok', 'retcode': 0, 'data': {'message_id': data.get('id')}}
        if action == 'get_status':
            data = {'online': status(self.config)['qqLoggedIn']}
        elif action == 'get_login_info':
            data = {'user_id': identity(self.config, self.bot_id), 'nickname': 'QQ 官方机器人'}
        elif action == 'get_version_info':
            data = {'app_name': 'QQ 官方开放平台', 'app_version': 'API v2'}
        elif action == 'get_group_list':
            # Only locally observed official groups; never claim an exhaustive remote listing.
            from .store import Store
            store = Store(self.config.data_dir / 'bot.db')
            with store._conn() as conn:
                rows = conn.execute('SELECT DISTINCT scope FROM messages WHERE scope LIKE ?',
                                    (f'group:qqofficial:{self.config.official_app_id}:%',)).fetchall()
            data = [{'group_id': row[0][6:], 'group_name': '官方群 ' + row[0].split(':')[-1][:12]} for row in rows]
        elif action in ('get_msg', 'get_forward_msg'):
            wanted = str(params.get('message_id') or params.get('id') or '')
            if action == 'get_forward_msg':
                wanted = raw_id(self.config, wanted)
                if not wanted.startswith('forward-'):
                    raise UnsupportedActionError(action, 'not_cached')
                wanted = wanted[8:]
            self.config.data_dir.mkdir(parents=True, exist_ok=True)
            self.inbox('init')
            with sqlite3.connect(self.config.data_dir / 'bot.db') as conn:
                row = conn.execute('SELECT event_json FROM official_inbox WHERE app_id=? AND '
                                   '(message_id=? OR json_extract(event_json,\'$.real_id\')=?) LIMIT 1',
                                   (self.config.official_app_id, wanted, wanted)).fetchone()
            if row is None:
                raise UnsupportedActionError(action, 'not_cached')
            cached = json.loads(row[0])
            data = {'messages': cached.get('official_forward_nodes') or []} if action == 'get_forward_msg' else cached
        else:
            raise UnsupportedActionError(action, 'unsupported')
        return {'status': 'ok', 'retcode': 0, 'data': data}


async def diagnose(config):
    result = status(config)
    if not result['credentialsConfigured']:
        return {**result, 'connected': False, 'error': result['gatewayError']}
    try:
        async with OfficialConnection(config) as client:
            await client.request('GET', '/gateway')
        return {**result, 'connected': True, 'authenticationVerified': True,
                'note': '鉴权与网关地址已验证；接收消息须启动机器人，未发送测试消息',
                'unsupportedActions': sorted(UNSUPPORTED)}
    except OfficialError as exc:
        return {**result, 'connected': False, 'error': str(exc)}


def reset(config):
    """Explicit operator retry after fixing a terminal platform state; no network activity."""
    state_path(config).unlink(missing_ok=True)
    _sessions.pop((str(config.source_path), config.official_app_id), None)

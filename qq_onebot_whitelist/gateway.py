"""Framework-neutral OneBot v11 connection, RPC and read-only compatibility checks."""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from urllib.parse import urlsplit

import websockets

PROVIDERS = {'external': '通用 OneBot v11', 'napcat': 'NapCat', 'llbot': 'LLBot',
             'snowluma': 'SnowLuma', 'lagrange': 'Lagrange.OneBot', 'qqofficial': 'QQ 官方机器人'}


def history_params(config, group_id, anchor=0, count=50, reverse_order=True) -> dict:
    """SnowLuma uses actual message IDs (including negative IDs), not sequences."""
    field = 'message_id' if config.onebot_provider == 'snowluma' else 'message_seq'
    return {'group_id': int(group_id), field: int(anchor or 0),
            'count': int(count), 'reverse_order': bool(reverse_order)}


def history_anchor(config, messages):
    if not messages:
        return None
    if config.onebot_provider == 'snowluma':
        oldest = min(messages, key=lambda m: (int(m.get('message_seq') or 0), int(m.get('time') or 0)))
        return oldest.get('message_id')
    return messages[0].get('message_seq') or messages[0].get('message_id')


class ActionError(RuntimeError):
    def __init__(self, action: str, retcode=None):
        self.action, self.retcode = action, retcode
        super().__init__(f'OneBot action {action} failed (retcode={retcode})')


class UnsupportedActionError(ActionError):
    pass


def managed(config) -> bool:
    return (config.onebot_provider == 'napcat' and config.onebot_manage_process
            and urlsplit(config.onebot_ws_url).hostname in ('127.0.0.1', 'localhost', '::1'))


def info(config) -> dict:
    disabled = set(config.onebot_disabled_actions)
    if config.onebot_provider == 'qqofficial':
        from .qq_official import UNSUPPORTED
        disabled.update(UNSUPPORTED)
    return {'gatewayProvider': config.onebot_provider,
            'gatewayName': PROVIDERS[config.onebot_provider],
            'gatewayManaged': managed(config) or (config.onebot_provider == 'snowluma' and config.onebot_start_installed_runtime),
            'gatewayWebuiUrl': config.onebot_webui_url,
            'gatewayProtocol': 'qqofficial' if config.onebot_provider == 'qqofficial' else 'onebot11',
            'disabledActions': sorted(disabled)}


def report_targets(config) -> list[tuple[str, str, object]]:
    if config.onebot_provider == 'qqofficial':
        from .qq_official import identity
        return [('send_private_msg', 'user_id', identity(config, uid)) for uid in sorted(config.official_report_users)] + [
            ('send_group_msg', 'group_id', identity(config, gid)) for gid in sorted(config.official_report_groups)]
    return [('send_private_msg', 'user_id', int(uid)) for uid in sorted(config.bot.whitelist_users)]


def connect(config, *, open_timeout=10, events=False):
    if config.onebot_provider == 'qqofficial':
        from .qq_official import OfficialConnection
        return OfficialConnection(config, events=events, open_timeout=open_timeout)
    options = {'open_timeout': open_timeout, 'max_size': config.onebot_max_message_mb * 1024 * 1024}
    if config.onebot_access_token:
        header_key = 'additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
        options[header_key] = {'Authorization': 'Bearer ' + config.onebot_access_token}
    class Connection:
        async def __aenter__(self):
            self.context = websockets.connect(config.onebot_ws_url, **options)
            ws = await self.context.__aenter__()
            ws._gateway_disabled_actions = config.onebot_disabled_actions
            return ws

        async def __aexit__(self, *args):
            return await self.context.__aexit__(*args)
    return Connection()


def normalize_event(event: dict) -> dict:
    """Normalize standard array/CQ messages without depending on a vendor's extra fields."""
    if not isinstance(event, dict):
        raise ValueError('OneBot event must be an object')
    result = dict(event)
    if isinstance(result.get('message'), str):
        import re
        def unescape(text):
            return text.replace('&#91;', '[').replace('&#93;', ']').replace('&#44;', ',').replace('&amp;', '&')
        parts, offset = [], 0
        for match in re.finditer(r'\[CQ:([A-Za-z0-9_]+)((?:,[^\]]*)?)\]', result['message']):
            if match.start() > offset:
                parts.append({'type': 'text', 'data': {'text': unescape(result['message'][offset:match.start()])}})
            data = {}
            for pair in match[2].lstrip(',').split(','):
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    data[key] = unescape(value)
            parts.append({'type': match[1], 'data': data})
            offset = match.end()
        if offset < len(result['message']):
            parts.append({'type': 'text', 'data': {'text': unescape(result['message'][offset:])}})
        result['message'] = parts
    if result.get('message_type') == 'group':
        result.setdefault('sender', {})
    return result


def checked_response(action: str, response: dict) -> dict:
    retcode = response.get('retcode', 0)
    if response.get('status') in ('failed', 'error') or str(retcode) not in ('0', 'None'):
        # Inspect the vendor message for classification, but never put it in logs (may contain secrets).
        reason = str(response.get('message') or response.get('wording') or '').lower()
        unsupported = str(retcode) in ('1404', '404', '10002', '10003') or any(
            word in reason for word in ('not supported', 'unsupported', 'unknown action', '不支持', '未实现'))
        raise (UnsupportedActionError if unsupported else ActionError)(action, retcode)
    result = dict(response)
    if action == 'get_msg' and isinstance(result.get('data'), dict):
        result['data'] = normalize_event(result['data'])
    if action in ('get_forward_msg', 'get_group_msg_history') and isinstance(result.get('data'), list):
        result['data'] = {'messages': result['data']}
    if action == 'get_forward_msg' and isinstance(result.get('data'), dict):
        nodes = result['data'].get('messages')
        if isinstance(nodes, list):
            result['data'] = dict(result['data'])
            result['data']['messages'] = [normalize_event({
                **node, 'message': node.get('message', node.get('content', [])),
                'user_id': node.get('user_id') or (node.get('sender') or {}).get('user_id', '')})
                for node in nodes if isinstance(node, dict)]
    return result


async def call(ws, action: str, params=None, *, timeout=15, echo=None) -> dict:
    if action in getattr(ws, '_gateway_disabled_actions', set()):
        raise UnsupportedActionError(action, 'disabled')
    if hasattr(ws, 'execute'):
        return await asyncio.wait_for(ws.execute(action, params or {}), timeout)
    echo = echo or uuid.uuid4().hex
    async def request():
        await ws.send(json.dumps({'action': action, 'params': params or {}, 'echo': echo}, ensure_ascii=False))
        while True:
            try:
                response = json.loads(await ws.recv())
            except (ValueError, TypeError):
                continue
            if isinstance(response, dict) and response.get('echo') == echo:
                return checked_response(action, response)
    return await asyncio.wait_for(request(), timeout)


async def probe(config) -> dict:
    if config.onebot_provider == 'qqofficial':
        from .qq_official import status
        return status(config)
    result = {**info(config), 'gatewayRunning': False, 'onebot': False,
              'qqLoggedIn': False, 'qqStatusKnown': False, 'qqNumber': '', 'qqNickname': ''}
    async with connect(config, open_timeout=2) as ws:
        result.update(gatewayRunning=True, onebot=True)
        try:
            status = (await call(ws, 'get_status', timeout=1)).get('data') or {}
            if isinstance(status.get('online'), bool):
                result.update(qqLoggedIn=status['online'], qqStatusKnown=True)
        except (ActionError, asyncio.TimeoutError):
            pass
        try:
            login = (await call(ws, 'get_login_info', timeout=1)).get('data') or {}
            result.update(qqNumber=str(login.get('user_id') or ''), qqNickname=str(login.get('nickname') or ''))
        except (ActionError, asyncio.TimeoutError):
            pass
    return result


def probe_sync(config) -> dict:
    try:
        return asyncio.run(asyncio.wait_for(probe(config), timeout=3.5))
    except Exception:
        return {**info(config), 'gatewayRunning': False, 'onebot': False,
                'qqLoggedIn': False, 'qqStatusKnown': False, 'qqNumber': '', 'qqNickname': ''}


async def diagnose(config, *, group_id=None) -> dict:
    """Only read-only actions. Does not log in, send messages or change membership."""
    if config.onebot_provider == 'qqofficial':
        from .qq_official import diagnose as official_diagnose
        return await official_diagnose(config)
    results = {}
    actions = [('get_version_info', {}), ('get_status', {}), ('get_login_info', {}), ('get_group_list', {})]
    if group_id:
        actions += [('get_group_msg_history', {'group_id': int(group_id), 'count': 1}),
                    ('get_group_root_files', {'group_id': int(group_id)})]
    try:
        async with connect(config, open_timeout=3) as ws:
            for action, params in actions:
                if action in config.onebot_disabled_actions:
                    results[action] = {'state': 'disabled'}
                    continue
                try:
                    response = await call(ws, action, params, timeout=3)
                    results[action] = {'state': 'supported'}
                    if action == 'get_version_info':
                        data = response.get('data') or {}
                        results[action]['implementation'] = str(data.get('app_name') or '')[:80]
                        results[action]['version'] = str(data.get('app_version') or '')[:80]
                except UnsupportedActionError:
                    results[action] = {'state': 'unsupported'}
                except asyncio.TimeoutError:
                    results[action] = {'state': 'timeout'}
                except ActionError as exc:
                    results[action] = {'state': 'failed', 'retcode': exc.retcode}
        return {**info(config), 'connected': True, 'actions': results}
    except Exception:
        return {**info(config), 'connected': False, 'actions': results,
                'error': '无法连接；请检查端点、Token 和框架运行状态'}

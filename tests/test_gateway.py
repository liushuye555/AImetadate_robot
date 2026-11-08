"""Shared protocol contract, tested without any QQ login or real framework process."""
import asyncio
import json

import pytest
import websockets

from qq_onebot_whitelist import gateway, control
from qq_onebot_whitelist.config import AppConfig, load_config


@pytest.mark.parametrize('provider', ['external', 'llbot', 'snowluma', 'lagrange'])
def test_external_profiles_never_start_napcat(tmp_path, monkeypatch, provider):
    (tmp_path / 'config.yaml').write_text(f'onebot:\n  provider: {provider}\n  manage_process: true\n')
    monkeypatch.setattr(control, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(control, 'RUN_DIR', tmp_path / 'run')
    monkeypatch.setattr(control, 'require_manager', lambda _: {'session': 'test'})
    monkeypatch.setattr(control.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('must not start NapCat'))
    assert control.ensure_gateway_running() is False
    assert control.ensure_napcat_running() is False
    assert not gateway.managed(load_config(tmp_path / 'config.yaml'))


def test_remote_napcat_does_not_start_local_process():
    config = AppConfig(onebot_ws_url='wss://example.invalid/onebot')
    assert not gateway.managed(config)


def test_config_keeps_token_out_of_repr_and_loads_project_env(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('onebot:\n  provider: snowluma\n  access_token_env: LOCAL_GATEWAY_TEST_KEY\n  ws_url: ws://127.0.0.1:38001/onebot\n')
    (tmp_path / '.env').write_text('LOCAL_GATEWAY_TEST_KEY=test-secret-not-for-output\n')
    config = load_config(config_path)
    assert config.onebot_access_token == 'test-secret-not-for-output'
    assert config.onebot_manage_process is False and config.onebot_webui_url == ''
    assert config.onebot_ws_url.endswith(':38001/onebot')
    assert config.onebot_access_token not in repr(config)
    assert config.onebot_access_token not in json.dumps(gateway.info(config))


@pytest.mark.parametrize('text', ['provider: unknown', 'protocol: milky', 'ws_url: http://localhost', 'max_message_mb: 0'])
def test_invalid_or_unimplemented_config_is_explicit(tmp_path, text):
    path = tmp_path / 'config.yaml'
    path.write_text('onebot:\n  ' + text + '\n')
    with pytest.raises(ValueError):
        load_config(path)


def test_cq_and_array_events_share_the_same_segments():
    array = [{'type': 'text', 'data': {'text': 'hello [x] '}},
             {'type': 'at', 'data': {'qq': '123'}},
             {'type': 'image', 'data': {'file': 'abc', 'url': 'https://example.invalid/a?x=1&y=2'}}]
    cq = 'hello &#91;x&#93; [CQ:at,qq=123][CQ:image,file=abc,url=https://example.invalid/a?x=1&amp;y=2]'
    assert gateway.normalize_event({'message': cq})['message'] == array
    assert gateway.normalize_event({'message': array})['message'] == array


@pytest.mark.parametrize('provider', ['napcat', 'llbot', 'snowluma', 'lagrange', 'external'])
def test_real_websocket_token_rpc_shapes_large_frames_and_offline_status(provider):
    async def scenario():
        calls = []
        async def endpoint(ws):
            headers = ws.request.headers if hasattr(ws, 'request') else ws.request_headers
            assert headers['Authorization'] == 'Bearer local-secret'
            async for packet in ws:
                request = json.loads(packet)
                action = request['action']
                calls.append(action)
                data = {'get_status': {'online': False, 'good': True},
                        'get_login_info': {'user_id': 42, 'nickname': 'cached offline identity'},
                        'get_version_info': {'app_name': provider, 'app_version': 'test'},
                        'get_group_list': [{'group_id': 7}],
                        'get_group_msg_history': [{'message': 'x' * 1800000}],
                        'get_forward_msg': [{'message': []}]}.get(action)
                # Broadcast events must not be mistaken for the RPC response.
                await ws.send(json.dumps({'post_type': 'meta_event'}))
                response = {'echo': request['echo'], 'status': 'ok', 'retcode': 0, 'data': data}
                if data is None:
                    response.update(status='failed', retcode=1404, message='unsupported action')
                await ws.send(json.dumps(response))
        async with websockets.serve(endpoint, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            config = AppConfig(onebot_provider=provider, onebot_ws_url=f'ws://127.0.0.1:{port}/onebot',
                               onebot_access_token='local-secret')
            state = await gateway.probe(config)
            assert state['onebot'] and state['gatewayRunning']
            assert state['qqStatusKnown'] and not state['qqLoggedIn']
            assert state['qqNumber'] == '42'  # login metadata alone must not imply online
            async with gateway.connect(config) as ws:
                response = await gateway.call(ws, 'get_group_msg_history')
                assert len(response['data']['messages'][0]['message']) == 1800000
                assert (await gateway.call(ws, 'get_forward_msg'))['data']['messages'][0]['message'] == []
                with pytest.raises(gateway.UnsupportedActionError):
                    await gateway.call(ws, 'get_group_root_files')
            result = await gateway.diagnose(config, group_id=7)
            assert result['connected']
            assert result['actions']['get_group_msg_history']['state'] == 'supported'
            assert result['actions']['get_group_root_files']['state'] == 'unsupported'
            assert all(not action.startswith(('send_', 'set_', 'delete_')) for action in calls)
            assert 'local-secret' not in json.dumps(result)
    asyncio.run(scenario())


def test_disabled_extension_never_gets_sent_and_timeout_is_bounded():
    class WS:
        _gateway_disabled_actions = {'get_group_msg_history'}
        async def send(self, packet):
            self.sent = packet
        async def recv(self):
            await asyncio.Future()
    async def scenario():
        ws = WS()
        with pytest.raises(gateway.UnsupportedActionError):
            await gateway.call(ws, 'get_group_msg_history')
        assert not hasattr(ws, 'sent')
        with pytest.raises(asyncio.TimeoutError):
            await gateway.call(ws, 'get_status', timeout=.02)
    asyncio.run(scenario())


def test_nonzero_retcode_is_not_silently_successful():
    with pytest.raises(gateway.ActionError):
        gateway.checked_response('get_group_list', {'status': 'ok', 'retcode': 100, 'data': []})


def test_forward_content_and_sender_variant_is_normalized():
    response = gateway.checked_response('get_forward_msg', {'data': [
        {'sender': {'user_id': 123}, 'content': 'text[CQ:image,file=x,url=https://example.invalid/x]'}]})
    node = response['data']['messages'][0]
    assert node['user_id'] == 123 and node['message'][1]['type'] == 'image'


def test_reply_message_cq_forward_is_visible_to_favorites():
    from qq_onebot_whitelist.favorites import _forward_ids_from_message
    response = gateway.checked_response('get_msg', {'data': {'message': '[CQ:forward,id=record-42]'}})
    assert _forward_ids_from_message(response['data']) == ['record-42']


def test_group_listing_reports_action_failure(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('onebot:\n  provider: external\n')
    monkeypatch.setattr(control, 'REPO_ROOT', tmp_path)
    class WS:
        async def send(self, packet):
            self.request = json.loads(packet)
        async def recv(self):
            return json.dumps({'echo': self.request['echo'], 'status': 'ok', 'retcode': 100, 'data': None})
    class Connection:
        async def __aenter__(self):
            return WS()
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(gateway, 'connect', lambda *args, **kwargs: Connection())
    with pytest.raises(gateway.ActionError):
        asyncio.run(control._fetch_groups_once())


@pytest.mark.parametrize('retcode,expected', [(0, 0), (100, 1)])
def test_report_waits_for_framework_ack(tmp_path, monkeypatch, capsys, retcode, expected):
    from qq_onebot_whitelist import daily_report
    from qq_onebot_whitelist.store import Store
    (tmp_path / 'config.yaml').write_text(
        f'onebot:\n  provider: external\nstorage:\n  data_dir: {tmp_path.as_posix()}\nreply:\n  whitelist_users: [42]\n')
    monkeypatch.setattr(control, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(daily_report, 'build_daily_resource_report', lambda *args, **kwargs: 'test report')
    class WS:
        async def send(self, packet):
            self.request = json.loads(packet)
            assert self.request['action'] == 'send_private_msg'
        async def recv(self):
            return json.dumps({'echo': self.request['echo'], 'status': 'ok', 'retcode': retcode})
    class Connection:
        async def __aenter__(self):
            return WS()
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(gateway, 'connect', lambda *args, **kwargs: Connection())
    assert control.cmd_report_send(None) == expected
    assert json.loads(capsys.readouterr().out)['ok'] is (retcode == 0)

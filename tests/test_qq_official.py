import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import websockets

from qq_onebot_whitelist import gateway, qq_official, config_bridge, control
from qq_onebot_whitelist.config import AppConfig, load_config
from qq_onebot_whitelist.policy import is_directly_mentioned
from qq_onebot_whitelist.store import Store


def config_for(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('onebot:\n  provider: qqofficial\nqq_official:\n  app_id: "123"\n'
                    '  allowed_groups: [GROUP]\n  report_groups: [GROUP]\n', encoding='utf-8')
    (tmp_path / '.env').write_text('QQBOT_APP_SECRET=fixture-secret\n')
    config = load_config(path)
    config.data_dir = tmp_path / 'data'
    return config


def test_secret_is_write_only_and_official_allowlists_are_namespaced(tmp_path):
    config = config_for(tmp_path)
    assert config.bot.whitelist_groups == {'qqofficial:123:GROUP'}
    assert 'fixture-secret' not in repr(config)
    assert 'fixture-secret' not in json.dumps(gateway.info(config))
    result = config_bridge.patch_config(config.source_path, {'qq_official': {'app_secret': 'new-secret'}})
    assert 'new-secret' not in json.dumps(result)
    assert 'app_secret' not in config.source_path.read_text()
    assert load_config(config.source_path).official_app_secret == 'new-secret'
    config_bridge.patch_config(config.source_path, {'qq_official': {'app_secret': ''}})
    assert load_config(config.source_path).official_app_secret == 'new-secret'
    assert all(f['default'] == '' for f in config_bridge.config_schema(result)
               if f['key'] == 'qq_official.app_secret')


def test_event_conversion_preserves_attachments_mentions_cards_and_nested_messages(tmp_path):
    config = config_for(tmp_path)
    event = qq_official.convert_event(config, 'GROUP_AT_MESSAGE_CREATE', {
        'id': 'MID', 'group_openid': 'GROUP', 'timestamp': '2026-10-28T12:00:00+08:00',
        'author': {'member_openid': 'USER', 'username': 'member', 'member_role': 'admin'},
        'content': 'hello <@all>', 'message_type': 103, 'attachments': [
            {'url': 'https://example.invalid/a.png', 'content_type': 'image/png'},
            {'url': 'https://example.invalid/b.zip', 'content_type': 'file', 'filename': 'b.zip', 'size': 42}],
        'ark_data': {'fields': {'jump_url': 'https://example.invalid/resource'}},
        'msg_elements': [{'content': 'nested text'}]}, 'BOT')
    assert event['group_id'] == 'qqofficial:123:GROUP'
    assert event['user_id'] == 'qqofficial:123:USER'
    assert event['sender']['role'] == 'admin'
    assert is_directly_mentioned(event)
    assert [s['type'] for s in event['message']].count('image') == 1
    assert any(s['data'].get('name') == 'b.zip' for s in event['message'])
    assert not any(s['data'].get('text') == 'nested text' for s in event['message'])
    assert qq_official.convert_event(config, 'UNRELATED', {}) is None


def test_official_never_sends_old_numeric_ids_or_other_application_ids(tmp_path):
    config = config_for(tmp_path)
    client = qq_official.OfficialConnection(config)
    async def scenario():
        for target in ('12345678', 'qqofficial:other:USER'):
            with pytest.raises(qq_official.OfficialError):
                await client.execute('send_private_msg', {'user_id': target, 'message': 'no network'})
        with pytest.raises(gateway.UnsupportedActionError):
            await gateway.call(client, 'get_group_msg_history', {})
    asyncio.run(scenario())
    assert gateway.report_targets(config) == [('send_group_msg', 'group_id', 'qqofficial:123:GROUP')]


@pytest.fixture
def api_server():
    calls = []
    state = {'reject': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.command, self.path, body, self.headers.get('Authorization')))
            if self.path == '/app/getAppAccessToken':
                assert body == {'appId': '123', 'clientSecret': 'fixture-secret'}
                data = {'access_token': 'fixture-token', 'expires_in': 7200}
            else:
                assert self.headers.get('Authorization') == 'QQBot fixture-token'
                data = {'code': 304064} if state['reject'] else ({'file_info': 'uploaded-image'} if self.path.endswith('/files') else {'id': 'SENT'})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        def do_GET(self):
            assert self.path == '/gateway'
            assert self.headers.get('Authorization') == 'QQBot fixture-token'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"url":"wss://official-fixture.invalid/gateway"}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_real_http_and_ws_auth_event_capture_reply_and_failure(tmp_path, monkeypatch, api_server):
    base, calls, api_state = api_server
    config = config_for(tmp_path)
    monkeypatch.setattr(qq_official, 'API_BASE', base)
    monkeypatch.setattr(qq_official, 'TOKEN_BASE', base)
    original_connect = websockets.connect
    async def scenario():
        async def endpoint(ws):
            await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 100}}))
            identify = json.loads(await ws.recv())
            assert identify['op'] == 2 and identify['d']['token'] == 'QQBot fixture-token'
            assert identify['d']['intents'] & (1 << 25)
            await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 1,
                                      'd': {'session_id': 'SESSION', 'user': {'id': 'BOT', 'username': 'Official'}}}))
            for _ in range(2):
                await ws.send(json.dumps({'op': 0, 't': 'GROUP_MESSAGE_CREATE', 's': 2,
                                          'd': {'id': 'MID', 'group_openid': 'GROUP',
                                                'author': {'member_openid': 'USER'}, 'content': 'resource https://example.invalid/x'}}))
            async for packet in ws:
                if json.loads(packet)['op'] == 1:
                    await ws.send('{"op":11,"d":null}')
        async with websockets.serve(endpoint, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            def connect(url, **options):
                assert url.startswith('wss://official-fixture.invalid/')
                return original_connect(f'ws://127.0.0.1:{port}', **options)
            monkeypatch.setattr(websockets, 'connect', connect)
            async with gateway.connect(config, events=True) as client:
                store = Store(config.data_dir / 'bot.db')
                from qq_onebot_whitelist.onebot import record_event, send_reply
                config.feature_image_processing = False
                events = [json.loads(await asyncio.wait_for(client.__anext__(), 2)) for _ in range(2)]
                assert record_event(store, events[0], config)
                assert not record_event(store, events[1], config)
                assert store.count_messages_after('group:qqofficial:123:GROUP', 0) == 1
                await send_reply(client, events[0], 'reply')
                assert calls[-1][1] == '/v2/groups/GROUP/messages'
                assert calls[-1][2]['msg_id'] == 'MID'
                assert calls[-1][2]['content'] == 'reply'
                await gateway.call(client, 'send_group_msg', {'group_id': events[0]['group_id'],
                                   'message': [{'type': 'image', 'data': {'url': 'https://example.invalid/image.png'}}]})
                assert calls[-2][1] == '/v2/groups/GROUP/files'
                assert calls[-1][2]['msg_type'] == 7
                api_state['reject'] = True
                with pytest.raises(qq_official.OfficialError):
                    await gateway.call(client, 'send_group_msg', {'group_id': events[0]['group_id'], 'message': 'report'})
                await asyncio.sleep(.15)
                assert qq_official.read_state(config)['allMessagesObserved']
            assert not qq_official.read_state(config)['online']
    asyncio.run(scenario())


def test_blocked_credentials_do_not_reconnect_automatically(tmp_path):
    config = config_for(tmp_path)
    qq_official.write_state(config, online=False, blocked=True, closeCode=4915)
    async def scenario():
        with pytest.raises(qq_official.OfficialFatalError):
            async with gateway.connect(config):
                pytest.fail('must not start')
    asyncio.run(scenario())
    assert qq_official.status(config)['gatewayError']
    qq_official.reset(config)
    assert not qq_official.read_state(config)


def test_terminal_close_keeps_backlog_and_stops_all_sends(tmp_path):
    config = config_for(tmp_path)
    client = qq_official.OfficialConnection(config, events=True)
    event = qq_official.convert_event(config, 'GROUP_MESSAGE_CREATE', {
        'id': 'PENDING', 'group_openid': 'GROUP', 'author': {'member_openid': 'USER'}, 'content': 'pending'})
    client.inbox('put', event)
    client.failure = qq_official.OfficialFatalError('blocked')
    client.done = True
    async def scenario():
        with pytest.raises(qq_official.OfficialFatalError):
            await client.__anext__()
        with pytest.raises(qq_official.OfficialFatalError):
            await client.execute('send_group_msg', {'group_id': event['group_id'], 'message': 'must not send'})
        assert client.inbox('next')['message_id'] == 'PENDING'
    asyncio.run(scenario())


def test_unconfigured_official_diagnosis_has_no_network(tmp_path):
    config = AppConfig(onebot_provider='qqofficial', source_path=tmp_path / 'config.yaml')
    result = asyncio.run(gateway.diagnose(config))
    assert not result['connected'] and not result['credentialsConfigured']
    assert not result['qqLoggedIn']


@pytest.mark.parametrize('count', [256, 257])
def test_burst_disconnect_is_durable_and_resume_does_not_skip_unprocessed_messages(tmp_path, count):
    config = config_for(tmp_path)
    client = qq_official.OfficialConnection(config, events=True)
    class Socket:
        def __aiter__(self):
            async def frames():
                yield json.dumps({'op': 0, 't': 'READY', 's': 1, 'd': {'session_id': 'SESSION'}})
                for index in range(count):
                    yield json.dumps({'op': 0, 't': 'GROUP_MESSAGE_CREATE', 's': index + 2,
                                      'd': {'id': str(index), 'group_openid': 'GROUP',
                                            'author': {'member_openid': 'USER'}, 'content': str(index)}})
            return frames()
    async def drain(connection):
        values = []
        async for packet in connection:
            event = json.loads(packet)
            values.append(event['message_id'])
            await connection.acknowledge(event)
        return values
    async def scenario():
        client.ws = Socket()
        await asyncio.wait_for(client._pump(), 15)
        assert qq_official._sessions[client.key]['seq'] == count + 1
        first = json.loads(await client.__anext__())
        assert first['message_id'] == '0'
        await client.acknowledge(first)
        # New connection / process can drain the persisted backlog without server replay.
        resumed = qq_official.OfficialConnection(config, events=True)
        resumed.done = True
        values = ['0'] + await asyncio.wait_for(drain(resumed), 20)
        assert values == [str(i) for i in range(count)]
    asyncio.run(scenario())


def test_quoted_image_is_not_attributed_to_the_person_quoting_it(tmp_path):
    config = config_for(tmp_path)
    event = qq_official.convert_event(config, 'GROUP_MESSAGE_CREATE', {
        'id': 'REPLY', 'group_openid': 'GROUP', 'author': {'member_openid': 'B'},
        'content': 'nice', 'message_type': 103,
        'message_scene': {'ext': ['ref_msg_idx=ORIGINAL', 'msg_idx=REF_REPLY', 'auth_token=private']},
        'msg_elements': [{'author': {'member_openid': 'A'}, 'content': 'old prompt',
                          'attachments': [{'url': 'https://example.invalid/old.png', 'content_type': 'image/png'}]}]})
    assert event['user_id'] == 'qqofficial:123:B'
    assert event['message'][0] == {'type': 'reply', 'data': {'id': 'ORIGINAL'}}
    assert all(s['type'] != 'image' for s in event['message'])
    assert 'old prompt' not in json.dumps(event['message'])
    assert 'private' not in json.dumps(event)
    fallback = qq_official.convert_event(config, 'GROUP_MESSAGE_CREATE', {
        'id': 'QUOTE', 'group_openid': 'GROUP', 'author': {'member_openid': 'B'},
        'message_type': 103, 'content': 'reply', 'msg_elements': [{'msg_idx': 'ORIGINAL', 'content': 'old'}]})
    assert fallback['message'][0] == {'type': 'reply', 'data': {'id': 'ORIGINAL'}}


def test_binding_credentials_are_saved_without_losing_existing_business_config(tmp_path):
    from qq_onebot_whitelist.official_binding import save_credentials
    config_for(tmp_path)
    before = config_bridge._load(tmp_path / 'config.yaml')
    assert save_credentials(tmp_path, [{'appId': '123', 'appSecret': 'bound-secret'}]) == '123'
    after = config_bridge._load(tmp_path / 'config.yaml')
    assert after['qq_official']['allowed_groups'] == before['qq_official']['allowed_groups']
    assert after['onebot']['provider'] == 'qqofficial'
    assert 'bound-secret' not in json.dumps(after)
    assert load_config(tmp_path / 'config.yaml').official_app_secret == 'bound-secret'


def test_binding_does_not_guess_between_multiple_apps(tmp_path):
    from qq_onebot_whitelist.official_binding import save_credentials
    (tmp_path / 'config.yaml').write_text('onebot:\n  provider: external\n')
    with pytest.raises(ValueError):
        save_credentials(tmp_path, [{'appId': '1', 'appSecret': 'first'}, {'appId': '2', 'appSecret': 'second'}])
    assert not (tmp_path / '.env').exists()

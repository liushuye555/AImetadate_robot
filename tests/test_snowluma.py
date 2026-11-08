"""Isolated deployment and migration tests for the SnowLuma backend."""
import asyncio
import hashlib
import json
import os
import platform
import zipfile

import pytest
import yaml

from qq_onebot_whitelist import snowluma
from qq_onebot_whitelist.config import AppConfig


def test_status_reply_requires_a_new_runtime_even_after_repeated_clicks(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    config = snowluma.runtime_dir(root) / 'config' / 'onebot.json'
    config.parent.mkdir(parents=True)
    config.write_text('{"statusCommand":{"enabled":true}}', encoding='utf-8')
    monkeypatch.setattr(snowluma.manager_owner, 'require_manager', lambda _: {'session': 'fixture'})
    monkeypatch.setattr(snowluma, 'status', lambda _: {'running': True})
    for _ in range(2):
        with pytest.raises(snowluma.DeploymentError, match='停止再启动'):
            snowluma.start(root)
    marker = root / 'run' / 'snowluma-status-restart-required'
    assert marker.exists()
    assert json.loads(config.read_text(encoding='utf-8'))['statusCommand']['enabled'] is False

    class Process:
        pid = 12345
        def poll(self):
            return None

    monkeypatch.setattr(snowluma, 'status', lambda _: {'running': False})
    monkeypatch.setattr(snowluma, '_installed', lambda _: True)
    ports = iter([False, True])
    monkeypatch.setattr(snowluma, '_port_open', lambda _: next(ports))
    monkeypatch.setattr(snowluma.subprocess, 'Popen', lambda *_, **__: Process())
    monkeypatch.setattr(snowluma.manager_owner, 'process_identity', lambda _: 'fixture-created')
    snowluma.start(root)
    assert not marker.exists()


@pytest.mark.parametrize(('app_name', 'online', 'accepted'), [
    ('SnowLuma', True, True), ('NapCat', True, False), ('SnowLuma', False, False)])
def test_live_websocket_migration_probe_checks_implementation_and_login(app_name, online, accepted):
    import websockets

    async def scenario():
        calls = []

        async def endpoint(ws):
            headers = ws.request.headers if hasattr(ws, 'request') else ws.request_headers
            assert headers['Authorization'] == 'Bearer fixture-only'
            async for packet in ws:
                request = json.loads(packet)
                calls.append(request['action'])
                data = {'get_version_info': {'app_name': app_name}, 'get_status': {'online': online},
                        'get_login_info': {'user_id': 123456}, 'get_group_list': []}[request['action']]
                await ws.send(json.dumps({'echo': request['echo'], 'status': 'ok', 'retcode': 0, 'data': data}))

        async with websockets.serve(endpoint, '127.0.0.1', 0) as server:
            config = AppConfig(onebot_provider='snowluma', onebot_access_token='fixture-only',
                               onebot_ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}')
            if accepted:
                assert (await snowluma._verify(config))['user_id'] == 123456
                assert 'get_group_list' in calls
            else:
                with pytest.raises(snowluma.DeploymentError):
                    await snowluma._verify(config)
            assert all(action.startswith('get_') for action in calls)

    asyncio.run(scenario())


def _archive(path, *, extra=()):
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, data in [
            ('node.exe', b'not executed'), ('index.mjs', b'not executed'),
            ('client/index.html', b'ui'), ('EULA.md', b'eula'),
            ('PRIVACY.md', b'privacy'), *extra,
        ]:
            bundle.writestr(name, data)
    return path


def _allow_switch(monkeypatch):
    # Avoid manager/runtime discovery: the tests use a temporary, stopped root.
    monkeypatch.setattr(snowluma, '_stop_for_switch', lambda root: None)


def _endpoint(root, account='123456', port=32123, token='fixture-token'):
    folder = snowluma.runtime_dir(root) / 'config'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'onebot_{account}.json').write_text(json.dumps({'networks': {
        'wsServers': [{'enabled': True, 'role': 'Universal', 'host': '127.0.0.1',
                       'port': port, 'path': '/ws', 'accessToken': token}]
    }}), encoding='utf-8')


def test_install_pins_digest_and_extracts_expected_layout(tmp_path, monkeypatch):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        pytest.skip('the pinned package is Windows x64 only')
    archive = _archive(tmp_path / 'fixture.zip')
    monkeypatch.setattr(snowluma, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())

    result = snowluma.install(tmp_path / 'app', archive=archive)
    target = snowluma.runtime_dir(tmp_path / 'app')
    assert result['installed'] is True
    assert all((target / item).is_file() for item in
               ('node.exe', 'index.mjs', 'client/index.html', 'EULA.md', 'PRIVACY.md'))
    assert json.loads((target / 'deployment.json').read_text())['sha256'] == snowluma.SHA256
    installed_config = json.loads((target / 'config/onebot.json').read_text())
    assert installed_config['networks']['wsServers'][0]['host'] == '127.0.0.1'
    assert installed_config['statusCommand']['enabled'] is False


def test_extract_rejects_zip_slip(tmp_path):
    archive = _archive(tmp_path / 'unsafe.zip', extra=(('../outside.txt', b'x'),))
    with pytest.raises(snowluma.DeploymentError, match='不安全'):
        snowluma._extract(archive, tmp_path / 'out')
    assert not (tmp_path / 'outside.txt').exists()


def test_repeat_install_preserves_existing_runtime_configuration(tmp_path, monkeypatch):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        pytest.skip('the pinned package is Windows x64 only')
    root = tmp_path / 'app'
    target = snowluma.runtime_dir(root)
    target.mkdir(parents=True)
    (target / 'node.exe').write_bytes(b'node')
    (target / 'index.mjs').write_text('index')
    (target / 'client').mkdir()
    (target / 'client/index.html').write_text('ui')
    (target / 'EULA.md').write_text('eula')
    (target / 'PRIVACY.md').write_text('privacy')
    config = target / 'config/onebot.json'
    config.parent.mkdir()
    config.write_text('{"custom":"preserve"}', encoding='utf-8')
    archive = _archive(tmp_path / 'unused.zip')
    monkeypatch.setattr(snowluma, '_download', lambda path: pytest.fail('must not download on repeat install'))

    result = snowluma.install(root, archive=archive)
    assert '保留' in result['message']
    assert config.read_text(encoding='utf-8') == '{"custom":"preserve"}'


def test_failed_digest_does_not_create_or_replace_provider(tmp_path, monkeypatch):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        pytest.skip('the pinned package is Windows x64 only')
    root = tmp_path / 'app'
    root.mkdir()
    before = root / 'config.yaml'
    before.write_text('onebot:\n  provider: napcat\n  ws_url: ws://127.0.0.1:3001\n', encoding='utf-8')
    archive = _archive(tmp_path / 'bad.zip')
    monkeypatch.setattr(snowluma, 'SHA256', '0' * 64)

    with pytest.raises(snowluma.DeploymentError, match='校验失败'):
        snowluma.install(root, archive=archive)
    assert yaml.safe_load(before.read_text(encoding='utf-8'))['onebot']['provider'] == 'napcat'
    assert not snowluma.runtime_dir(root).exists()


def test_switch_and_restore_preserve_other_data_and_hide_token(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'app'
    root.mkdir()
    config_path = root / 'config.yaml'
    original = {
        'onebot': {'provider': 'napcat', 'ws_url': 'ws://localhost:3001',
                   'access_token_env': 'NAPCAT_TOKEN', 'disabled_actions': ['send_file']},
        'reply': {'whitelist_groups': ['group-1']},
        'knowledge': {'enabled': True, 'groups': {'group-1': {'enabled': True}}},
    }
    config_path.write_text(yaml.safe_dump(original, allow_unicode=True), encoding='utf-8')
    (root / '.env').write_text('NAPCAT_TOKEN=old-token\nKEEP=value\n', encoding='utf-8')
    secret = 'fictional-snowluma-token'
    _endpoint(root, token=secret)
    _allow_switch(monkeypatch)

    async def verified(config):
        assert config.onebot_provider == 'snowluma'
        assert config.onebot_access_token == secret
        return {'user_id': '123456'}

    monkeypatch.setattr(snowluma, '_verify', verified)
    monkeypatch.delenv(snowluma.TOKEN_ENV, raising=False)
    result = snowluma.switch(root)
    assert result['gatewayProvider'] == 'snowluma'
    captured = capsys.readouterr()
    assert secret not in json.dumps(result) + captured.out + captured.err
    changed = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert changed['onebot']['access_token_env'] == snowluma.TOKEN_ENV
    assert changed['onebot']['provider'] == 'snowluma'
    assert changed['reply'] == original['reply']
    assert changed['knowledge'] == original['knowledge']
    assert (root / '.env').read_text(encoding='utf-8') == (
        'NAPCAT_TOKEN=old-token\nKEEP=value\n' + f'{snowluma.TOKEN_ENV}={secret}\n')

    snowluma.restore(root)
    restored = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert restored == original
    assert (root / '.env').read_text(encoding='utf-8').startswith('NAPCAT_TOKEN=old-token\nKEEP=value\n')


@pytest.mark.parametrize(('account', 'user_id'), [('123456', '654321'), (None, '123456')])
def test_switch_rejects_wrong_expected_or_multiple_accounts(tmp_path, monkeypatch, account, user_id):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'config.yaml').write_text('reply:\n  whitelist_groups: ["keep"]\n', encoding='utf-8')
    _endpoint(root, account='123456', port=32001, token='token-a')
    if account is None:
        _endpoint(root, account='654321', port=32002, token='token-b')
    _allow_switch(monkeypatch)

    async def verified(config):
        if account is None:
            return {'user_id': '123456' if config.onebot_access_token == 'token-a' else '654321'}
        return {'user_id': user_id}

    monkeypatch.setattr(snowluma, '_verify', verified)
    monkeypatch.delenv(snowluma.TOKEN_ENV, raising=False)
    with pytest.raises(snowluma.DeploymentError, match='未改动|多个在线连接'):
        snowluma.switch(root, account=account)
    assert yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8')) == {
        'reply': {'whitelist_groups': ['keep']}}
    assert not (root / 'run/gateway-before-snowluma.json').exists()


def test_stop_uses_verified_process_identity(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    record = {'pid': 4321, 'created': 'identity', 'session': 'session'}
    path = root / 'run/snowluma-process.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record), encoding='utf-8')
    monkeypatch.setattr(snowluma.manager_owner, 'require_manager', lambda root: {'session': 'session'})
    monkeypatch.setattr(snowluma.manager_owner, 'is_process_alive', lambda pid, created: True)
    seen = []
    monkeypatch.setattr(snowluma.manager_owner, 'terminate_process_tree',
                        lambda pid, created: seen.append((pid, created)) or True)

    result = snowluma.stop(root)
    assert seen == [(4321, 'identity')]
    assert '保持运行' in result['message']
    assert not path.exists()


def test_second_account_switch_keeps_original_provider_backup(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    root.mkdir()
    original = {'onebot': {'provider': 'napcat', 'ws_url': 'ws://127.0.0.1:3001',
                           'custom_option': 'original'},
                'reply': {'whitelist_groups': ['keep']}}
    (root / 'config.yaml').write_text(yaml.safe_dump(original), encoding='utf-8')
    _endpoint(root, account='123456', port=32101, token='first-token')
    _endpoint(root, account='654321', port=32102, token='second-token')
    _allow_switch(monkeypatch)

    async def verified(config):
        return {'user_id': '123456' if config.onebot_access_token == 'first-token' else '654321'}

    monkeypatch.setattr(snowluma, '_verify', verified)
    monkeypatch.delenv(snowluma.TOKEN_ENV, raising=False)
    snowluma.switch(root, account='123456')
    backup_path = root / 'run/gateway-before-snowluma.json'
    first_backup = json.loads(backup_path.read_text(encoding='utf-8'))
    snowluma.switch(root, account='654321')

    assert json.loads(backup_path.read_text(encoding='utf-8')) == first_backup
    assert first_backup == {'onebot': original['onebot'], 'present': True}
    current = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))
    assert current['onebot']['ws_url'] == 'ws://127.0.0.1:32102/ws'
    assert current['reply'] == original['reply']


def test_stop_for_switch_records_manual_stop_and_manager_session(tmp_path, monkeypatch):
    from qq_onebot_whitelist import control

    root = tmp_path / 'app'
    root.mkdir()
    monkeypatch.setattr(control, 'REPO_ROOT', root)
    monkeypatch.setattr(control, 'owned_bot_running', lambda: True)
    monkeypatch.setattr(snowluma.manager_owner, 'require_manager', lambda path: {'session': 'manager-session'})
    calls = []
    monkeypatch.setattr(snowluma.manager_owner, 'terminate_owned_tree',
                        lambda path, session: calls.append((path, session)) or True)

    snowluma._stop_for_switch(root)

    assert calls == [(root, 'manager-session')]
    assert (root / 'run/manual-stop').read_text(encoding='utf-8') == 'gateway migration'
    assert not (root / 'run/bot.pid').exists()


def test_stop_for_switch_failure_keeps_config_unchanged(tmp_path, monkeypatch):
    from qq_onebot_whitelist import control

    root = tmp_path / 'app'
    root.mkdir()
    config = root / 'config.yaml'
    config.write_text('onebot:\n  provider: napcat\nreply:\n  whitelist_groups: [keep]\n', encoding='utf-8')
    original = config.read_bytes()
    monkeypatch.setattr(control, 'REPO_ROOT', root)
    monkeypatch.setattr(control, 'owned_bot_running', lambda: True)
    monkeypatch.setattr(snowluma.manager_owner, 'require_manager', lambda path: {'session': 'session-7'})
    calls = []
    monkeypatch.setattr(snowluma.manager_owner, 'terminate_owned_tree',
                        lambda path, session: calls.append((path, session)) or False)

    with pytest.raises(snowluma.DeploymentError, match='未能停止'):
        snowluma._stop_for_switch(root)
    assert calls == [(root, 'session-7')]
    assert config.read_bytes() == original
    assert (root / 'run/manual-stop').exists()


def _control_root(tmp_path, monkeypatch, *, provider='snowluma', start_runtime=True):
    from qq_onebot_whitelist import control
    root = tmp_path / 'manager-root'
    root.mkdir()
    (root / 'config.yaml').write_text(yaml.safe_dump({'onebot': {
        'provider': provider, 'start_installed_runtime': start_runtime}}), encoding='utf-8')
    run_dir = root / 'run'
    run_dir.mkdir()
    monkeypatch.setattr(control, 'REPO_ROOT', root)
    monkeypatch.setattr(control, 'RUN_DIR', run_dir)
    return control, root, run_dir


def test_ensure_gateway_running_starts_snowluma_without_starting_napcat(tmp_path, monkeypatch):
    from qq_onebot_whitelist import snowluma as backend
    control, root, _ = _control_root(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, 'status', lambda path: {'running': False})
    starts = []
    monkeypatch.setattr(backend, 'start', lambda path: starts.append(path) or {'ok': True})
    monkeypatch.setattr(control, 'ensure_napcat_running',
                        lambda **kwargs: pytest.fail('SnowLuma configuration must not start NapCat'))

    assert control.ensure_gateway_running() is True
    assert starts == [root]


@pytest.mark.parametrize('marker', ['manual-stop', 'snowluma-user-stop'])
def test_ensure_gateway_running_honors_stop_markers(tmp_path, monkeypatch, marker):
    from qq_onebot_whitelist import snowluma as backend
    control, root, run_dir = _control_root(tmp_path, monkeypatch)
    (run_dir / marker).write_text('stopped', encoding='utf-8')
    monkeypatch.setattr(backend, 'status', lambda path: {'running': False})
    monkeypatch.setattr(backend, 'start', lambda path: pytest.fail('stop marker must suppress recovery'))

    assert control.ensure_gateway_running() is False


@pytest.mark.parametrize(('provider', 'expect_error'), [('external', False), ('snowluma', True)])
def test_stop_respects_provider_when_business_bot_is_running(tmp_path, monkeypatch, provider, expect_error):
    from qq_onebot_whitelist import control

    root = tmp_path / 'app'
    root.mkdir()
    monkeypatch.setattr(control, 'REPO_ROOT', root)
    (root / 'config.yaml').write_text(yaml.safe_dump({'onebot': {'provider': provider}}), encoding='utf-8')
    monkeypatch.setattr(snowluma.manager_owner, 'require_manager', lambda path: {'session': 'manager'})
    monkeypatch.setattr(control, 'owned_bot_running', lambda: True)
    monkeypatch.setattr(snowluma.manager_owner, 'is_process_alive', lambda pid, created: True)
    terminated = []
    monkeypatch.setattr(snowluma.manager_owner, 'terminate_process_tree',
                        lambda pid, created: terminated.append((pid, created)) or True)
    process_file = root / 'run/snowluma-process.json'
    process_file.parent.mkdir()
    process_file.write_text(json.dumps({'pid': 98, 'created': 'snow-id', 'session': 'mgr'}), encoding='utf-8')

    if expect_error:
        with pytest.raises(snowluma.DeploymentError, match='机器人仍在运行'):
            snowluma.stop(root)
        assert terminated == []
        assert process_file.exists()
    else:
        snowluma.stop(root)
        assert terminated == [(98, 'snow-id')]
        assert not process_file.exists()


def test_disable_status_command_preserves_global_and_per_account_configs(tmp_path):
    config_dir = snowluma.runtime_dir(tmp_path) / 'config'
    config_dir.mkdir(parents=True)
    expected = []
    for name in ('onebot.json', 'onebot_123456.json', 'onebot_654321.json'):
        payload = {
            'customTopLevel': {'keep': True},
            'networks': {'wsServers': [{'port': 3001, 'accessToken': 'fixture'}]},
            'statusCommand': {'enabled': True, 'trigger': '#sl', 'prefix': '.',
                              'customSetting': {'retained': 'yes'}},
        }
        path = config_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        expected.append((path, payload))

    snowluma.disable_status_command(tmp_path)

    for path, original in expected:
        updated = json.loads(path.read_text(encoding='utf-8'))
        assert updated['statusCommand'] == {**original['statusCommand'], 'enabled': False}
        assert updated['networks'] == original['networks']
        assert updated['customTopLevel'] == original['customTopLevel']
        first_write = path.read_bytes()
        snowluma.disable_status_command(tmp_path)
        assert path.read_bytes() == first_write


def test_disable_status_command_rejects_malformed_config_without_overwrite(tmp_path):
    config_dir = snowluma.runtime_dir(tmp_path) / 'config'
    config_dir.mkdir(parents=True)
    malformed = config_dir / 'onebot_123456.json'
    original = b'{ "statusCommand": '
    malformed.write_bytes(original)

    with pytest.raises(snowluma.DeploymentError, match='JSON|json|配置'):
        snowluma.disable_status_command(tmp_path)
    assert malformed.read_bytes() == original

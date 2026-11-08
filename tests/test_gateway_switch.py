"""Safe, reversible provider switching without launching gateway processes."""
import asyncio
import json

import pytest
import websockets
import yaml

from qq_onebot_whitelist import gateway_switch
from qq_onebot_whitelist.config import AppConfig, load_config
from qq_onebot_whitelist.snowluma import DeploymentError


def _root(tmp_path, *, provider='napcat'):
    root = tmp_path / 'app'
    root.mkdir()
    cfg = {'onebot': {'provider': provider, 'protocol': 'onebot11',
                      'ws_url': 'ws://127.0.0.1:3001', 'manage_process': True,
                      'access_token_env': 'OLD_TOKEN', 'disabled_actions': ['legacy_action']},
           'reply': {'whitelist_groups': ['preserve-group']},
           'knowledge': {'enabled': True, 'groups': {'1': {'enabled': True}}}}
    (root / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    (root / '.env').write_text('OLD_TOKEN=old-secret\nNEW_TOKEN=new-secret\nKEEP=value\n', encoding='utf-8')
    return root, cfg


@pytest.mark.parametrize('provider', ['external', 'napcat', 'llbot', 'snowluma', 'lagrange'])
def test_switch_validates_candidate_using_project_env(tmp_path, monkeypatch, provider):
    root, _ = _root(tmp_path)
    monkeypatch.delenv('NEW_TOKEN', raising=False)
    seen = []

    async def verify(config):
        seen.append(config)

    monkeypatch.setattr(gateway_switch, 'verify', verify)
    result = gateway_switch.switch(root, {'onebot': {
        'provider': provider, 'protocol': 'onebot11', 'ws_url': 'ws://127.0.0.1:3002/ws',
        'access_token_env': 'NEW_TOKEN', 'manage_process': provider == 'napcat'}})

    assert result['gatewayProvider'] == provider
    assert len(seen) == 1
    assert seen[0].onebot_provider == provider
    assert seen[0].onebot_ws_url == 'ws://127.0.0.1:3002/ws'
    assert seen[0].onebot_access_token == 'new-secret'
    saved = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))['onebot']
    assert saved['provider'] == provider
    assert saved['access_token_env'] == 'NEW_TOKEN'
    if provider != 'snowluma':
        assert saved['start_installed_runtime'] is False
    assert (root / 'run/manual-stop').exists()


def test_restore_preserves_non_gateway_data_and_original_env(tmp_path, monkeypatch):
    root, original = _root(tmp_path)
    env_before = (root / '.env').read_bytes()
    monkeypatch.setattr(gateway_switch, 'verify', lambda config: asyncio.sleep(0))

    gateway_switch.switch(root, {'onebot': {'provider': 'llbot', 'ws_url': 'ws://127.0.0.1:3002'}})
    gateway_switch.restore(root)

    restored = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))
    assert restored['onebot'] == original['onebot']
    assert restored['reply'] == original['reply']
    assert restored['knowledge'] == original['knowledge']
    assert (root / '.env').read_bytes() == env_before


def test_failed_validation_and_network_check_leave_config_and_env_unchanged(tmp_path, monkeypatch):
    root, _ = _root(tmp_path)
    config_path = root / 'config.yaml'
    before_config = config_path.read_bytes()
    before_env = (root / '.env').read_bytes()

    with pytest.raises(DeploymentError, match='无效'):
        gateway_switch.switch(root, {'onebot': {'provider': 'external', 'max_message_mb': 0}})
    assert config_path.read_bytes() == before_config
    assert (root / '.env').read_bytes() == before_env
    assert (root / 'run/manual-stop').exists()

    async def network_error(config):
        raise DeploymentError('local fixture failed')

    monkeypatch.setattr(gateway_switch, 'verify', network_error)
    with pytest.raises(DeploymentError, match='local fixture failed'):
        gateway_switch.switch(root, {'onebot': {'provider': 'llbot', 'ws_url': 'ws://127.0.0.1:3002'}})
    assert config_path.read_bytes() == before_config
    assert (root / '.env').read_bytes() == before_env


def test_second_switch_does_not_replace_first_backup(tmp_path, monkeypatch):
    root, original = _root(tmp_path)
    monkeypatch.setattr(gateway_switch, 'verify', lambda config: asyncio.sleep(0))
    gateway_switch.switch(root, {'onebot': {'provider': 'llbot'}})
    backup = root / 'run/gateway-before-switch.json'
    first_backup = backup.read_bytes()
    gateway_switch.switch(root, {'onebot': {'provider': 'llbot'}})

    assert backup.read_bytes() == first_backup
    assert json.loads(first_backup) == {'present': True, 'onebot': original['onebot']}


def test_switching_to_a_different_provider_updates_restore_point(tmp_path, monkeypatch):
    root, _ = _root(tmp_path)
    monkeypatch.setattr(gateway_switch, 'verify', lambda config: asyncio.sleep(0))
    gateway_switch.switch(root, {'onebot': {'provider': 'llbot'}})
    after_first_switch = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))['onebot']
    gateway_switch.switch(root, {'onebot': {'provider': 'external'}})

    backup = json.loads((root / 'run/gateway-before-switch.json').read_text(encoding='utf-8'))
    assert backup == {'present': True, 'onebot': after_first_switch}
    gateway_switch.restore(root)
    restored = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))
    assert restored['onebot'] == after_first_switch


def test_switch_refuses_if_gateway_section_changes_during_verification(tmp_path, monkeypatch):
    root, _ = _root(tmp_path)
    config_path = root / 'config.yaml'

    async def concurrent_change(config):
        current = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        current['onebot']['ws_url'] = 'ws://127.0.0.1:39999'
        config_path.write_text(yaml.safe_dump(current), encoding='utf-8')

    monkeypatch.setattr(gateway_switch, 'verify', concurrent_change)
    with pytest.raises(DeploymentError, match='发生变化'):
        gateway_switch.switch(root, {'onebot': {'provider': 'llbot'}})
    changed = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert changed['onebot']['ws_url'] == 'ws://127.0.0.1:39999'
    assert changed['onebot']['provider'] == 'napcat'
    assert (root / 'run/manual-stop').exists()
    assert not (root / 'run/gateway-before-switch.json').exists()


@pytest.mark.parametrize(('connected', 'raises'), [(True, False), (False, True)])
def test_official_verify_uses_mocked_local_diagnosis(monkeypatch, connected, raises):
    from qq_onebot_whitelist import qq_official

    calls = []

    async def diagnose(config):
        calls.append(config)
        return {'connected': connected}

    monkeypatch.setattr(qq_official, 'diagnose', diagnose)
    config = AppConfig(onebot_provider='qqofficial')
    if raises:
        with pytest.raises(DeploymentError, match='官方通道检查未通过'):
            asyncio.run(gateway_switch.verify(config))
    else:
        asyncio.run(gateway_switch.verify(config))
    assert calls == [config]


@pytest.mark.parametrize(('online', 'user_id', 'group_ok', 'expected_calls'), [
    (False, 42, True, ['get_version_info', 'get_status', 'get_login_info']),
    (True, '', True, ['get_version_info', 'get_status', 'get_login_info']),
    (True, 42, False, ['get_version_info', 'get_status', 'get_login_info', 'get_group_list']),
    (True, 42, True, ['get_version_info', 'get_status', 'get_login_info', 'get_group_list']),
])
def test_verify_reads_only_and_requires_live_account_and_groups(online, user_id, group_ok, expected_calls):
    async def scenario():
        calls = []

        async def endpoint(ws):
            async for packet in ws:
                request = json.loads(packet)
                action = request['action']
                calls.append(action)
                data = {'get_version_info': {'app_name': 'fixture', 'app_version': '1'},
                        'get_status': {'online': online}, 'get_login_info': {'user_id': user_id},
                        'get_group_list': [{'group_id': 1}] if group_ok else None}[action]
                response = {'echo': request['echo'], 'status': 'ok', 'retcode': 0, 'data': data}
                if action == 'get_group_list' and not group_ok:
                    response.update(status='failed', retcode=100, message='fixture error')
                await ws.send(json.dumps(response))

        async with websockets.serve(endpoint, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            config = load_config_from_values(f'ws://127.0.0.1:{port}/onebot')
            should_fail = (not online) or (not user_id) or (not group_ok)
            if should_fail:
                with pytest.raises(Exception):
                    await gateway_switch.verify(config)
            else:
                await gateway_switch.verify(config)
            assert calls == expected_calls
            assert all(action.startswith('get_') for action in calls)

    asyncio.run(scenario())


def load_config_from_values(url):
    # The verifier only needs an in-memory OneBot profile and never reads project files.
    return AppConfig(onebot_provider='external', onebot_ws_url=url)

import sys
from qq_onebot_whitelist import onebot, manager_owner


def test_direct_bot_entry_refuses_before_lock_or_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['onebot', '--config', 'unused.yaml'])
    def refuse(_):
        raise manager_owner.ManagerRequiredError('manager required')
    monkeypatch.setattr(manager_owner, 'require_manager', refuse)
    def forbidden(*args, **kwargs):
        raise AssertionError('unmanaged bot must not read config, acquire lock or run')
    monkeypatch.setattr(onebot, '_acquire_single_instance_lock', forbidden)
    monkeypatch.setattr(onebot, 'load_config', forbidden)
    monkeypatch.setattr(onebot.asyncio, 'run', forbidden)
    assert onebot.main() == 1
    assert 'manager required' in capsys.readouterr().out

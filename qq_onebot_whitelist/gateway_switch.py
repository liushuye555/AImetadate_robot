"""Verified provider switching, with reversible configuration-only changes."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile

import yaml

from . import gateway
from .config import load_config
from .config_bridge import _load
from .snowluma import DeploymentError, _guard, _read_json, _stop_for_switch, _write_json

FIELDS = {'provider', 'protocol', 'manage_process', 'start_installed_runtime', 'ws_url',
          'webui_url', 'access_token_env', 'max_message_mb', 'disabled_actions'}


def _prepare(root: Path, mapping: dict):
    """Validate against the real project env without changing config.yaml."""
    data = _load(root / 'config.yaml')
    if mapping.get('present', True):
        data['onebot'] = mapping['onebot']
    else:
        data.pop('onebot', None)
    fd, name = tempfile.mkstemp(prefix='.gateway-candidate-', suffix='.yaml', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        config = load_config(name)
    finally:
        Path(name).unlink(missing_ok=True)
    return config


async def verify(config) -> None:
    if config.onebot_provider == 'qqofficial':
        from .qq_official import diagnose
        result = await asyncio.wait_for(diagnose(config), timeout=15)
        if not result.get('connected'):
            raise DeploymentError('QQ 官方通道检查未通过，请先完成绑定并确认平台权限。')
        return
    async with gateway.connect(config, open_timeout=3) as ws:
        await gateway.call(ws, 'get_version_info', timeout=3)
        state = (await gateway.call(ws, 'get_status', timeout=3)).get('data') or {}
        login = (await gateway.call(ws, 'get_login_info', timeout=3)).get('data') or {}
        if state.get('online') is not True or not login.get('user_id'):
            raise DeploymentError('目标框架已连接，但 QQ 尚未确认在线；请先完成登录。')
        await gateway.call(ws, 'get_group_list', timeout=3)


def _commit(root: Path, mapping: dict) -> None:
    """Replace exactly the gateway section, preserving business config at commit time."""
    data = _load(root / 'config.yaml')
    if mapping['present']:
        data['onebot'] = mapping['onebot']
    else:
        data.pop('onebot', None)
    fd, name = tempfile.mkstemp(prefix='.gateway-save-', suffix='.yaml', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        os.replace(name, root / 'config.yaml')
    finally:
        Path(name).unlink(missing_ok=True)


def _snapshot(root: Path) -> dict:
    data = _load(root / 'config.yaml')
    return {'present': 'onebot' in data, 'onebot': data.get('onebot')}


def switch(root: Path, patch: dict) -> dict:
    root = Path(root)
    if not isinstance(patch, dict) or set(patch) != {'onebot'} or not isinstance(patch['onebot'], dict):
        raise DeploymentError('切换操作只接受接入框架设置，请先保存其他设置。')
    changes = patch['onebot']
    if set(changes) - FIELDS:
        raise DeploymentError('接入设置包含不支持的项目。')
    with _guard(root):
        _stop_for_switch(root)
        previous = _snapshot(root)
        target = {**(previous['onebot'] or {}), **changes}
        provider = str(target.get('provider') or 'napcat').lower()
        target['provider'] = provider
        target['protocol'] = 'qqofficial' if provider == 'qqofficial' else 'onebot11'
        if provider != 'snowluma':
            target['start_installed_runtime'] = False
        mapping = {'present': True, 'onebot': target}
        try:
            config = _prepare(root, mapping)
        except Exception as exc:
            raise DeploymentError('接入设置无效，请检查框架、连接地址和消息大小。') from exc
        if provider == 'snowluma':
            from .snowluma import disable_status_command, status
            disable_status_command(root)
            if (root / 'run' / 'snowluma-status-restart-required').exists() and status(root)['running']:
                raise DeploymentError('已关闭 #sl 自动回复配置，请重启 SnowLuma 后重新切换。')
        try:
            asyncio.run(verify(config))
        except DeploymentError:
            raise
        except Exception as exc:
            raise DeploymentError('目标连接检查未通过，原配置保持不变。请检查服务、登录状态和 Token。') from exc
        current = _snapshot(root)
        if current != previous:
            raise DeploymentError('接入配置在检查期间发生变化，已取消切换；请刷新设置后重试。')
        if mapping != previous:
            _write_json(root / 'run' / 'gateway-before-switch.json', previous)
            _commit(root, mapping)
        return {'ok': True, 'gatewayProvider': provider,
                'message': f'已检查并切换到 {gateway.PROVIDERS[provider]}。请在概览启动机器人；数据和报告保留。'}


def restore(root: Path) -> dict:
    root = Path(root)
    with _guard(root):
        _stop_for_switch(root)
        mapping = _read_json(root / 'run' / 'gateway-before-switch.json')
        if not isinstance(mapping.get('present'), bool) or 'onebot' not in mapping:
            raise DeploymentError('没有找到上次框架切换的备份。')
        if mapping['present'] and mapping['onebot'] is not None and not isinstance(mapping['onebot'], dict):
            raise DeploymentError('接入配置备份无效，未覆盖当前设置。')
        try:
            _prepare(root, mapping)
        except Exception as exc:
            raise DeploymentError('原接入配置已无法使用，请检查配置备份。') from exc
        _commit(root, mapping)
        return {'ok': True, 'message': '已恢复上次框架配置。请确认原服务运行后，在概览启动机器人。'}

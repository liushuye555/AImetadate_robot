"""Pinned Windows deployment and verified migration for the external SnowLuma runtime."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import secrets
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request
import zipfile

from . import gateway, manager_owner
from .config import load_config
from .config_bridge import _load, patch_config, patch_env

VERSION = '2.4.2'
ASSET = f'SnowLuma-v{VERSION}-win-x64.zip'
DOWNLOAD_URL = f'https://github.com/SnowLuma/SnowLuma/releases/download/v{VERSION}/{ASSET}'
SHA256 = '0912926c5e73260f35b000278a8658493fc9452f36782c32fa86f0e825bad81a'
TOKEN_ENV = 'SNOWLUMA_ONEBOT_TOKEN'
WEBUI_URL = 'http://127.0.0.1:5099/'


class DeploymentError(RuntimeError):
    """A safe, user-facing operational failure (no upstream response bodies)."""


def runtime_dir(root: Path) -> Path:
    return Path(root) / 'runtime' / 'snowluma'


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def _guard(root: Path):
    """Serialize install and process/config mutations across manager commands."""
    path = Path(root) / 'run' / 'snowluma.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DeploymentError('另一项 SnowLuma 操作正在进行，请稍后重试。') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _installed(root: Path) -> bool:
    folder = runtime_dir(root)
    return all((folder / part).is_file() for part in
               ('node.exe', 'index.mjs', 'client/index.html', 'EULA.md', 'PRIVACY.md'))


def status(root: Path) -> dict:
    record = _read_json(Path(root) / 'run' / 'snowluma-process.json')
    running = bool(record.get('created') and manager_owner.is_process_alive(record.get('pid'), record['created']))
    return {'ok': True, 'installed': _installed(root), 'running': running,
            'version': _read_json(runtime_dir(root) / 'deployment.json').get('version', ''),
            'webuiUrl': WEBUI_URL, 'logPath': str(Path(root) / 'logs' / 'snowluma.log'),
            'message': 'SnowLuma 运行中' if running else ('SnowLuma 已安装' if _installed(root) else '尚未安装 SnowLuma')}


def _download(path: Path) -> None:
    request = urllib.request.Request(DOWNLOAD_URL, headers={'User-Agent': 'QQ-OneBot-Manager'})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=30) as response, path.open('wb') as output:
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 256 * 1024 * 1024 or time.monotonic() - started > 600:
                raise DeploymentError('下载超时或文件大小异常，请稍后重试。')
            output.write(chunk)


def _extract(archive: Path, folder: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > 1024 * 1024 * 1024:
            raise DeploymentError('发行包大小异常。')
        for item in entries:
            path = PurePosixPath(item.filename.replace('\\', '/'))
            if (path.is_absolute() or '..' in path.parts or any(':' in part for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise DeploymentError('发行包包含不安全的文件路径。')
        bundle.extractall(folder)


def install(root: Path, *, archive: Path | None = None) -> dict:
    """Download/check/extract atomically. Never execute downloaded code during install."""
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise DeploymentError('内置部署目前支持 Windows x64；其他系统可连接自行部署的 OneBot 服务。')
    root = Path(root)
    with _guard(root):
        if _installed(root):
            return {**status(root), 'message': 'SnowLuma 已安装，保留现有登录和配置。'}
        destination = runtime_dir(root)
        if destination.exists():
            raise DeploymentError('安装目录已存在但不完整，请先检查 runtime/snowluma，避免覆盖已有数据。')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='snowluma-install-', dir=destination.parent) as temporary:
            temporary = Path(temporary)
            downloaded = archive or temporary / ASSET
            if archive is None:
                _download(downloaded)
            with downloaded.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != SHA256:
                raise DeploymentError('发行包校验失败，未安装；请重新下载。')
            extracted = temporary / 'package'
            extracted.mkdir()
            _extract(downloaded, extracted)
            if not all((extracted / part).is_file() for part in
                       ('node.exe', 'index.mjs', 'client/index.html', 'EULA.md', 'PRIVACY.md')):
                raise DeploymentError('发行包结构不完整，未安装。')
            token = secrets.token_urlsafe(32)
            _write_json(extracted / 'config' / 'onebot.json', {'networks': {
                'httpServers': [], 'httpClients': [], 'wsClients': [], 'wsServers': [{
                    'name': 'manager-local', 'enabled': True, 'host': '127.0.0.1', 'port': 3001,
                    'path': '/', 'role': 'Universal', 'accessToken': token,
                    'messageFormat': 'array', 'reportSelfMessage': False}]},
                'statusCommand': {'enabled': False}})
            _write_json(extracted / 'config' / 'runtime.json',
                        {'webuiPort': 5099, 'webuiHost': '127.0.0.1', 'hookAutoLoad': False})
            _write_json(extracted / 'deployment.json', {'version': VERSION, 'sha256': SHA256, 'source': DOWNLOAD_URL})
            os.replace(extracted, destination)
        return {**status(root), 'message': 'SnowLuma 已安装。点击启动，再在管理页确认协议并接入 QQ；尚未切换机器人。'}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.3):
            return True
    except OSError:
        return False


def disable_status_command(root: Path) -> int:
    """Disable the framework's own chat reply without altering network credentials."""
    import re
    folder = runtime_dir(root) / 'config'
    files = [folder / 'onebot.json'] + sorted(
        path for path in folder.glob('onebot_*.json') if re.fullmatch(r'onebot_[0-9]+\.json', path.name))
    pending = []
    for path in files:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError()
            setting = raw.get('statusCommand', {})
            if not isinstance(setting, dict):
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise DeploymentError('SnowLuma 配置无法读取，未覆盖原文件；请先检查管理页中的账号配置。') from exc
        if setting.get('enabled') is False:
            continue
        raw['statusCommand'] = {**setting, 'enabled': False}
        pending.append((path, raw))
    for path, raw in pending:
        _write_json(path, raw)
    if pending:
        marker = Path(root) / 'run' / 'snowluma-status-restart-required'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('status command configuration changed', encoding='utf-8')
    return len(pending)


def start(root: Path) -> dict:
    root = Path(root)
    session = manager_owner.require_manager(root)
    with _guard(root):
        (root / 'run' / 'snowluma-user-stop').unlink(missing_ok=True)
        disable_status_command(root)
        if status(root)['running']:
            if (root / 'run' / 'snowluma-status-restart-required').exists():
                raise DeploymentError('已关闭 #sl 自动回复配置，请停止再启动 SnowLuma 使修改生效。')
            return {**status(root), 'message': 'SnowLuma 已经运行，可打开管理页。'}
        if not _installed(root):
            raise DeploymentError('请先安装 SnowLuma。')
        if _port_open(5099):
            raise DeploymentError('5099 端口已被其他程序占用，未启动第二个实例。')
        folder = runtime_dir(root)
        env = os.environ.copy()
        # Explicit browser consent, plus manual selection of a QQ process in WebUI.
        for name in ('SNOWLUMA_ACCEPT_EULA', 'SNOWLUMA_ACCEPT_PRIVACY'):
            env.pop(name, None)
        env.pop('SNOWLUMA_HOOK_AUTOLOAD', None)
        env.update(SNOWLUMA_WEBUI_HOST='127.0.0.1', SNOWLUMA_WEBUI_PORT='5099')
        log_path = root / 'logs' / 'snowluma.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('ab') as log:
            process = subprocess.Popen([str(folder / 'node.exe'), str(folder / 'index.mjs')],
                cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        created = manager_owner.process_identity(process.pid)
        if not created:
            process.terminate()
            raise DeploymentError('SnowLuma 未能启动，请打开运行日志查看原因。')
        _write_json(root / 'run' / 'snowluma-process.json',
                    {'pid': process.pid, 'created': created, 'session': session['session']})
        (root / 'run' / 'snowluma-status-restart-required').unlink(missing_ok=True)
        for _ in range(80):
            if process.poll() is not None:
                raise DeploymentError('SnowLuma 启动失败，请打开运行日志查看原因。')
            if _port_open(5099):
                return {**status(root), 'message': 'SnowLuma 已启动。初始管理密码见运行日志；请在管理页确认协议并手动选择 QQ 进程接入。'}
            time.sleep(.1)
        return {**status(root), 'message': 'SnowLuma 进程已启动，管理页尚在初始化；请查看运行日志后打开管理页。'}


def stop(root: Path) -> dict:
    root = Path(root)
    manager_owner.require_manager(root)
    with _guard(root):
        from . import control
        if (root.resolve() == control.REPO_ROOT.resolve() and control.owned_bot_running()
                and load_config(root / 'config.yaml').onebot_provider == 'snowluma'):
            raise DeploymentError('机器人仍在运行；请先切换到其他接入或停止机器人，再停止 SnowLuma。')
        (root / 'run' / 'snowluma-user-stop').write_text('user stopped', encoding='utf-8')
        record = _read_json(root / 'run' / 'snowluma-process.json')
        if status(root)['running'] and not manager_owner.terminate_process_tree(record['pid'], record['created']):
            raise DeploymentError('未能停止 SnowLuma，进程身份校验未通过或仍在运行。')
        (root / 'run' / 'snowluma-process.json').unlink(missing_ok=True)
        return {**status(root), 'message': 'SnowLuma 已停止；桌面 QQ 保持运行。'}


def _stop_for_switch(root: Path) -> None:
    """Pause the business bot while keeping the manager and SnowLuma alive."""
    from . import control
    running = root.resolve() == control.REPO_ROOT.resolve() and control.owned_bot_running()
    session = manager_owner.require_manager(root) if running else None
    (root / 'run').mkdir(parents=True, exist_ok=True)
    (root / 'run' / 'manual-stop').write_text('gateway migration', encoding='utf-8')
    if running and not manager_owner.terminate_owned_tree(root, session['session']):
        raise DeploymentError('原机器人未能停止，未修改接入配置。')
    if running:
        (root / 'run' / 'bot.pid').unlink(missing_ok=True)


def _candidates(root: Path, account: str | None) -> list[tuple[str, str, str]]:
    config_dir = runtime_dir(root) / 'config'
    if account and (not account.isascii() or not account.isdigit()):
        raise DeploymentError('账号应为数字 QQ 号。')
    files = [config_dir / f'onebot_{account}.json'] if account else sorted(config_dir.glob('onebot_[0-9]*.json'))
    if not files:
        files = [config_dir / 'onebot.json']
    candidates = []
    for file in files:
        raw = _read_json(file)
        for endpoint in (raw.get('networks') or {}).get('wsServers', []):
            if not isinstance(endpoint, dict) or not endpoint.get('enabled', True):
                continue
            if str(endpoint.get('role', '')).lower() != 'universal':
                continue
            host = str(endpoint.get('host', ''))
            if host not in ('127.0.0.1', 'localhost', '::1', '0.0.0.0', '::'):
                continue
            port = endpoint.get('port')
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                continue
            path = str(endpoint.get('path', '/'))
            if not path.startswith('/') or '?' in path or '#' in path or any(c in path for c in '\r\n'):
                continue
            token = endpoint.get('accessToken')
            if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
                continue
            target_host = '[::1]' if host in ('::', '::1') else '127.0.0.1'
            expected = file.stem[7:] if file.stem.startswith('onebot_') else ''
            entry = (f'ws://{target_host}:{port}{path}', token, expected)
            if entry not in candidates:
                candidates.append(entry)
    if not candidates:
        raise DeploymentError('没有找到可用的本机双向连接。请先在 SnowLuma 管理页接入 QQ 并启用 WebSocket 服务。')
    return candidates


async def _verify(config) -> dict:
    async with gateway.connect(config, open_timeout=3) as ws:
        version = (await gateway.call(ws, 'get_version_info', timeout=3)).get('data') or {}
        if 'snowluma' not in str(version.get('app_name', '')).lower():
            raise DeploymentError('连接的服务不是 SnowLuma，未切换配置。')
        status = (await gateway.call(ws, 'get_status', timeout=3)).get('data') or {}
        login = (await gateway.call(ws, 'get_login_info', timeout=3)).get('data') or {}
        if status.get('online') is not True or not str(login.get('user_id') or '').isdigit():
            raise DeploymentError('SnowLuma 的 QQ 账号尚未在线，请先完成登录和进程接入。')
        # Required for group collection; extended history/file actions are checked separately.
        await gateway.call(ws, 'get_group_list', timeout=3)
        return login


def switch(root: Path, *, account: str | None = None) -> dict:
    root = Path(root)
    with _guard(root):
        _stop_for_switch(root)
        disable_status_command(root)
        if (root / 'run' / 'snowluma-status-restart-required').exists() and status(root)['running']:
            raise DeploymentError('已关闭 #sl 自动回复配置，请停止再启动 SnowLuma 后重新切换。')
        path = root / 'config.yaml'
        config = load_config(path)
        verified = []
        for url, token, expected in _candidates(root, account):
            candidate = replace(config, onebot_provider='snowluma', onebot_ws_url=url,
                                onebot_access_token=token, onebot_disabled_actions=set(), onebot_manage_process=False)
            try:
                login = asyncio.run(_verify(candidate))
                if expected and str(login['user_id']) != expected:
                    continue
                verified.append((url, token, login))
            except Exception:
                continue
        if not verified:
            raise DeploymentError('连接检查未通过，原配置未改动。请确认 SnowLuma 已接入在线 QQ、连接已启用且端口未冲突。')
        if len(verified) != 1:
            raise DeploymentError('发现多个在线连接，请在 SnowLuma 中只保留一个目标连接，或使用 --account 指定 QQ 号。')
        url, token, login = verified[0]
        if os.environ.get(TOKEN_ENV, token) != token:
            raise DeploymentError('系统环境中的 SnowLuma Token 与目标不一致，请移除旧环境设置后重开管理器。')
        _stop_for_switch(root)
        before = _load(path)
        previous = before.get('onebot')
        # Keep the pre-SnowLuma provider even when selecting a different QQ account.
        if not (isinstance(previous, dict) and previous.get('provider') == 'snowluma'):
            snapshot = {'onebot': previous, 'present': 'onebot' in before}
            _write_json(root / 'run' / 'gateway-before-snowluma.json', snapshot)
            _write_json(root / 'run' / 'gateway-before-switch.json', snapshot)
        patch_env(root / '.env', {TOKEN_ENV: token})
        patch_config(path, {'onebot': {'provider': 'snowluma', 'protocol': 'onebot11',
            'manage_process': False, 'start_installed_runtime': True, 'ws_url': url, 'webui_url': WEBUI_URL,
            'access_token_env': TOKEN_ENV, 'disabled_actions': []}})
        return {'ok': True, 'message': '已切换到 SnowLuma，连接与 QQ 在线检查通过。请在概览启动机器人；已有数据和报告保留。',
                'gatewayProvider': 'snowluma', 'webuiUrl': WEBUI_URL}


def restore(root: Path) -> dict:
    import yaml
    root = Path(root)
    with _guard(root):
        _stop_for_switch(root)
        backup = _read_json(root / 'run' / 'gateway-before-snowluma.json')
        if not isinstance(backup.get('present'), bool) or 'onebot' not in backup:
            raise DeploymentError('没有找到切换前的接入配置备份。')
        path = root / 'config.yaml'
        data = _load(path)
        if backup['present']:
            data['onebot'] = backup['onebot']
        else:
            data.pop('onebot', None)
        fd, temporary = tempfile.mkstemp(prefix='.restore-gateway-', dir=root, suffix='.yaml')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
            load_config(temporary)  # Validate before replacing the live configuration.
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {'ok': True, 'message': '已恢复上次接入配置。请在概览启动机器人；SnowLuma 可单独停止。'}

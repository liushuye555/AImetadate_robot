"""One-shot Tencent QR binding. Secrets stay in pipes and the project's .env."""
from __future__ import annotations

import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .config import load_config
from .config_bridge import patch_config


def page(root: Path, message: str, image='', url=''):
    target = root / 'run' / 'qq-official-bind.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                      '<meta http-equiv="refresh" content="3"><title>连接 QQ 官方机器人</title>'
                      '<style>body{background:#191925;color:#ececf4;font:18px system-ui;max-width:650px;'
                      'margin:50px auto;text-align:center}img{width:360px;border-radius:18px}a{color:#9fbffc}</style>'
                      '<h1>连接 QQ 官方机器人</h1><p>' + html.escape(message) + '</p>'
                      + (f'<img src="{html.escape(Path(image).name)}?t={time.time_ns()}"><p>用手机 QQ 扫码并按官方页面提示选择机器人。</p>' if image else '')
                      + (f'<p><a href="{html.escape(url, quote=True)}">也可打开官方连接页面</a></p>' if url else '')
                      + '<p>这是官方机器人绑定；原来的数据库、图库和报告保留。</p></html>', encoding='utf-8')
    return target


def save_credentials(root: Path, credentials: list[dict]) -> str:
    config_path = root / 'config.yaml'
    current = load_config(config_path)
    valid = [c for c in credentials if isinstance(c, dict) and c.get('appId') and c.get('appSecret')]
    selected = next((c for c in valid if str(c['appId']) == current.official_app_id), None)
    if selected is None and len(valid) == 1:
        selected = valid[0]
    if selected is None:
        raise ValueError('请在设置中指定 AppID 后重新绑定，避免选错多个机器人')
    app_id = str(selected['appId'])
    if not app_id.isdigit():
        raise ValueError('官方机器人 AppID 无效')
    patch_config(config_path, {'onebot': {'provider': 'qqofficial', 'protocol': 'qqofficial', 'manage_process': False,
                                         'webui_url': 'https://q.qq.com/'},
                               'qq_official': {'app_id': app_id, 'app_secret': str(selected['appSecret'])}})
    from .qq_official import reset
    reset(load_config(config_path))
    return app_id


def worker(root: Path) -> int:
    node = shutil.which('node')
    helper = root / 'scripts' / 'qq-official' / 'bind.mjs'
    if not node or not (helper.parent / 'node_modules' / '@tencent-connect' / 'qqbot-connector').exists():
        page(root, '缺少扫码组件；请安装 scripts/qq-official 的依赖，或在设置中手工填写 AppID/AppSecret。')
        return 1
    image = root / 'run' / 'qq-official-qr.png'
    process = subprocess.Popen([node, str(helper), str(image)], cwd=helper.parent,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for line in process.stdout:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            phase = value.get('phase')
            if phase == 'waiting':
                from urllib.parse import urlsplit
                url = str(value.get('url') or '')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or parsed.hostname != 'q.qq.com':
                    raise ValueError('官方连接地址校验失败')
                page(root, '等待手机 QQ 扫码', str(image), url)
            elif phase == 'credentials':
                app_id = save_credentials(root, value.get('credentials') or [])
                page(root, f'绑定成功，AppID：{app_id}。回到管理器填写官方群/用户 OpenID 和日报接收者，再启动机器人。')
                return 0
            elif phase == 'expired':
                page(root, '二维码已过期，请重新点击“连接 QQ 官方机器人”。')
                return 1
            elif phase == 'failed':
                page(root, '官方扫码连接失败或已超时，请重试；也可以手工填写 AppID/AppSecret。')
                return 1
        page(root, '扫码组件已退出，请重新连接。')
        return 1
    except Exception:
        page(root, '绑定未完成，请核对 AppID 或重新连接；密钥未显示在页面中。')
        return 1
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        image.unlink(missing_ok=True)


def launch(root: Path) -> dict:
    # Refuse a second concurrent binding; do not overwrite a live QR session.
    from .manager_owner import process_identity, is_process_alive
    pid_file = root / 'run' / 'qq-official-bind.pid.json'
    try:
        previous = json.loads(pid_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    target = root / 'run' / 'qq-official-bind.html'
    if previous.get('created') and is_process_alive(previous.get('pid'), previous.get('created')) and target.exists():
        return {'ok': True, 'path': str(target), 'pid': previous['pid']}
    target = page(root, '正在请求官方绑定二维码，请稍候……')
    process = subprocess.Popen([sys.executable, '-m', 'qq_onebot_whitelist.control', 'official-bind', '--worker'],
                               cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    pid_file.write_text(json.dumps({'pid': process.pid, 'created': process_identity(process.pid)}), encoding='utf-8')
    return {'ok': True, 'path': str(target), 'pid': process.pid}

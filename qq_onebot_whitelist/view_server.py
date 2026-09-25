"""本地图库服务：http 提供 data/view 静态页面，并接收图库页面的导出请求。

只绑定 127.0.0.1。导出是状态变更操作，需要页面内嵌的构建 token
（随视图重建轮换，防其他网页跨站盲发）；响应不带 CORS 头，
file:// 页面读不到结果，因此导出按钮只在本服务提供的页面里可用。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

_MAX_BODY = 64 * 1024
_ORIENTATIONS = {'landscape', 'portrait', 'square'}
_OUT_NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,80}$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_JOB_KEEP_LINES = 200

_MIME = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
    '.bmp': 'image/bmp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
}

_job_lock = threading.Lock()
_job: dict = {'status': 'idle'}


def _build_state_path(project_dir: Path) -> Path:
    return project_dir / 'data' / 'view-build-state.json'


def accepted_tokens(project_dir: Path) -> set[str]:
    """当前接受的页面构建 token（含最近几轮，容忍未刷新的旧页面）。"""
    try:
        state = json.loads(_build_state_path(project_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return set()
    tokens = {str(t) for t in (state.get('build_token_history') or [])}
    if state.get('build_token'):
        tokens.add(str(state['build_token']))
    return tokens


def _validate_params(payload: dict) -> tuple[list[str], str | None]:
    argv = ['--json']
    out_dir = str(payload.get('out_dir') or '').strip().strip('"').strip()
    if out_dir:
        # 用户指定绝对路径（资源管理器"复制文件地址"会带引号，上面已剥掉）
        if not re.match(r'^([A-Za-z]:[\\/]|\\\\)', out_dir):
            return [], '目标文件夹需要绝对路径，如 D:\\datasets\\my-lora'
        if len(out_dir) > 240:
            return [], '路径过长'
        argv += ['--out-dir', out_dir]
    out = str(payload.get('out') or '').strip()
    if out:
        if not _OUT_NAME_RE.match(out):
            return [], '目录名只允许字母、数字和 . _ -'
        argv += ['--out', out]
    for key, flag in (('user', '--user'), ('source', '--source'), ('category', '--category')):
        values = payload.get(key) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return [], f'{key} 参数格式错误'
        for value in values[:20]:
            value = str(value).strip()[:120]
            if value:
                argv += [flag, value]
    orientation = str(payload.get('orientation') or '').strip()
    if orientation:
        if orientation not in _ORIENTATIONS:
            return [], f'未知方向 {orientation!r}'
        argv += ['--orientation', orientation]
    for key, flag, ceiling in (('min_side', '--min-side', 8192), ('limit', '--limit', 100000)):
        value = payload.get(key)
        if value is None or value == '':
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            return [], f'{key} 必须是整数'
        if not 1 <= value <= ceiling:
            return [], f'{key} 超出范围'
        argv += [flag, str(value)]
    for key, flag in (('since', '--since'), ('until', '--until')):
        value = str(payload.get(key) or '').strip()
        if value:
            if not _DATE_RE.match(value):
                return [], f'{key} 需要 YYYY-MM-DD 格式'
            argv += [flag, value]
    keyword = str(payload.get('keyword') or '').strip()[:200]
    if keyword:
        argv += ['--keyword', keyword]
    if payload.get('dup_only'):
        argv += ['--dup-only']
    if payload.get('link'):
        argv += ['--link']
    if payload.get('no_captions'):
        argv += ['--no-captions']
    if payload.get('dry_run'):
        argv += ['--dry-run']
    return argv, None


def _run_export(project_dir: Path, argv: list[str]) -> None:
    tail: list[str] = []
    pkg_root = str(Path(__file__).resolve().parents[1])
    try:
        proc = subprocess.Popen(
            argv, cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'PYTHONUTF8': '1',
                 'PYTHONPATH': pkg_root + os.pathsep + os.environ.get('PYTHONPATH', '')},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as exc:
        with _job_lock:
            _job.update({'status': 'error', 'returncode': -1,
                         'log_tail': [f'{type(exc).__name__}: {exc}'],
                         'finished_at': time.strftime('%Y-%m-%d %H:%M:%S')})
        return
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            del tail[:-_JOB_KEEP_LINES]
    code = proc.wait()
    summary = None
    for line in reversed(tail):
        if line.startswith('EXPORT_JSON '):
            try:
                summary = json.loads(line[len('EXPORT_JSON '):])
            except ValueError:
                summary = None
            break
    with _job_lock:
        _job.update({'status': 'done' if code == 0 else 'error', 'returncode': code,
                     'summary': summary, 'log_tail': tail[-30:],
                     'finished_at': time.strftime('%Y-%m-%d %H:%M:%S')})


def make_handler(project_dir: Path) -> type[BaseHTTPRequestHandler]:
    view_root = (project_dir / 'data' / 'view').resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'ViewServer/1'

        def log_message(self, fmt: str, *args: object) -> None:  # 静默访问日志
            pass

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, rel: str) -> None:
            base = str(view_root) + os.sep
            target = (view_root / PurePosixPath(rel)).resolve()
            # 必须仍在视图目录内：Windows 上 resolve 会把 %5C 解码出的反斜杠当分隔符
            if not str(target).startswith(base):
                self._json(403, {'error': 'forbidden'})
                return
            if target.is_dir():
                target = target / 'index.html'
            if not target.is_file():
                self._json(404, {'error': 'not found'})
                return
            mime = _MIME.get(target.suffix.lower(), 'application/octet-stream')
            data = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            # html 不缓存：重建后立即生效；chunk URL 自带构建指纹，其余短缓存即可
            self.send_header('Cache-Control', 'no-cache' if target.suffix == '.html' else 'max-age=600')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server 命名约定)
            path = unquote(urlsplit(self.path).path)
            if path == '/api/export/status':
                with _job_lock:
                    snapshot = dict(_job)
                self._json(200, snapshot)
                return
            if path == '/api/health':
                self._json(200, {'ok': True})
                return
            if path in ('/', '/view', '/view/'):
                self.send_response(302)
                self.send_header('Location', '/view/index.html')
                self.end_headers()
                return
            if path.startswith('/view/'):
                self._static(path[len('/view/'):])
                return
            self._json(404, {'error': 'not found'})

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != '/api/export':
                self._json(404, {'error': 'not found'})
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_BODY:
                self._json(400, {'error': '请求体过大或为空'})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {'error': 'JSON 解析失败'})
                return
            if not isinstance(payload, dict):
                self._json(400, {'error': 'JSON 解析失败'})
                return
            tokens = accepted_tokens(project_dir)
            if not tokens:
                self._json(403, {'error': '视图尚未构建，请先运行维护构建页面'})
                return
            if str(payload.get('token') or '') not in tokens:
                self._json(403, {'error': '页面版本过期，请刷新页面后重试'})
                return
            with _job_lock:
                if _job.get('status') == 'running':
                    self._json(409, {'error': '已有导出任务进行中，请等它结束'})
                    return
                argv, error = _validate_params(payload)
                if error:
                    self._json(400, {'error': error})
                    return
                _job.clear()
                _job.update({'status': 'running',
                             'started_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                             'dry_run': bool(payload.get('dry_run')),
                             'params': {k: payload.get(k) for k in
                                        ('user', 'category', 'orientation', 'min_side',
                                         'since', 'until', 'keyword', 'dup_only',
                                         'out_dir', 'out')
                                        if payload.get(k) is not None}})
            argv = [sys.executable, '-m', 'qq_onebot_whitelist.export_dataset',
                    '--project-dir', str(project_dir)] + argv
            threading.Thread(target=_run_export, args=(project_dir, argv),
                             daemon=True, name='export-job').start()
            self._json(202, {'status': 'running'})

    return Handler


def make_server(project_dir: Path, port: int) -> ThreadingHTTPServer:
    project_dir = Path(project_dir).resolve()
    httpd = ThreadingHTTPServer(('127.0.0.1', port), make_handler(project_dir))
    httpd.daemon_threads = True
    return httpd


def serve(project_dir: Path, port: int) -> None:
    try:
        httpd = make_server(project_dir, port)
    except OSError as exc:
        print(f'view server: 端口 {port} 不可用（{exc}），图库 http 服务未启动')
        return
    print(f'view server: http://127.0.0.1:{port}/view/ （仅本机可访问）')
    httpd.serve_forever()

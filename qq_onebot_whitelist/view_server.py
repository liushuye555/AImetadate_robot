"""本地图库服务：实时数据库查询、归档图片、缩略图、报告页面与导出。

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
import secrets
import hashlib
import shutil
import sqlite3
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, parse_qs, urlencode

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
_thumbnail_slots = threading.BoundedSemaphore(2)


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
    if 'gallery_query' in payload:
        from .gallery_store import normalize_query
        try:
            query = normalize_query(payload['gallery_query'])
        except ValueError as exc:
            return [], str(exc)
        argv += ['--gallery-query', json.dumps(query, ensure_ascii=False)]
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
    project_dir = project_dir.resolve()
    view_root = (project_dir / 'data' / 'view').resolve()
    session_token = secrets.token_urlsafe(32)

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
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _html(self, body: str) -> None:
            data = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def _local_request(self) -> bool:
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host not in ('127.0.0.1', 'localhost', '::1'):
                self._json(403, {'error': '仅允许本机访问'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host'):
                self._json(403, {'error': '请求来源不正确'})
                return False
            return True

        def _image(self, image_id: int, thumbnail: bool) -> None:
            from .gallery_store import image_path
            try:
                path = image_path(project_dir, image_id)
                stat = path.stat()
                key = hashlib.sha256(f'{path}:{stat.st_mtime_ns}:{stat.st_size}:thumb-v1'.encode()).hexdigest()
                etag = '"' + key + ('-thumb' if thumbnail else '') + '"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304)
                    self.send_header('ETag', etag)
                    self.end_headers()
                    return
                if thumbnail:
                    cache = project_dir / 'data' / 'cache' / 'gallery-thumbnails'
                    cache.mkdir(parents=True, exist_ok=True)
                    target = cache / (key + '.jpg')
                    with _thumbnail_slots:
                        if not target.exists():
                            from PIL import Image, ImageOps
                            with Image.open(path) as img:
                                img.seek(0)
                                img.thumbnail((480, 480))
                                thumb = ImageOps.exif_transpose(img).convert('RGB')
                                with tempfile.NamedTemporaryFile(dir=cache, suffix='.tmp', delete=False) as tmp:
                                    tmp_path = Path(tmp.name)
                                try:
                                    thumb.save(tmp_path, format='JPEG', quality=82)
                                    tmp_path.replace(target)
                                finally:
                                    tmp_path.unlink(missing_ok=True)
                    path = target
                with path.open('rb') as stream:
                    self.send_response(200)
                    self.send_header('Content-Type', _MIME.get(path.suffix.lower(), 'application/octet-stream'))
                    self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                    self.send_header('Cache-Control', 'private, max-age=600')
                    self.send_header('ETag', etag)
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    if self.command != 'HEAD':
                        shutil.copyfileobj(stream, self.wfile)
            except (FileNotFoundError, OSError, ValueError):
                self._json(404, {'error': '原图不存在或暂时无法读取'})

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
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server 命名约定)
            if not self._local_request():
                return
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/gallery/') or path.startswith('/media/images/'):
                from .gallery_store import facets, query_images, image_details
                try:
                    if path == '/api/gallery/meta':
                        self._json(200, {**facets(project_dir), 'token': session_token})
                    elif path in ('/api/gallery/images', '/api/gallery/browse', '/api/gallery/group'):
                        params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        if any(len(v) != 1 for v in params.values()):
                            raise ValueError('筛选条件不能重复')
                        from .gallery_browse import browse_images, image_group
                        reader = {'/api/gallery/images': query_images,
                                  '/api/gallery/browse': browse_images,
                                  '/api/gallery/group': image_group}[path]
                        self._json(200, reader(project_dir, {k: v[0] for k,v in params.items()}))
                    elif match := re.fullmatch(r'/api/gallery/images/([1-9][0-9]{0,17})', path):
                        self._json(200, image_details(project_dir, int(match[1])))
                    elif match := re.fullmatch(r'/media/images/([1-9][0-9]{0,17})(/thumbnail)?', path):
                        self._image(int(match[1]), bool(match[2]))
                    else:
                        self._json(404, {'error': 'not found'})
                except FileNotFoundError as exc:
                    self._json(404, {'error': str(exc)})
                except ValueError as exc:
                    self._json(400, {'error': str(exc)})
                except sqlite3.Error:
                    self._json(503, {'error': '图片数据库暂时不可用，请稍后重试'})
                return
            if path == '/view/gallery.html':
                from .database_gallery import gallery_html
                self._html(gallery_html(project_dir))
                return
            if path in ('/view/', '/view/index.html'):
                from .gallery_store import facets
                from .database_gallery import hub_html
                try:
                    self._html(hub_html(project_dir, facets(project_dir)))
                except sqlite3.Error:
                    self._json(503, {'error': '图片数据库暂时不可用'})
                return
            # Historic category URLs now query the catalogue, including categories with no directory.
            if path.startswith('/view/') and (path.endswith('/index.html') or path.endswith('/')):
                from .build_image_view import CATEGORY_NAMES, ALL_GALLERY_DIR, _SAVED_ROOT
                category = path[len('/view/'):].removesuffix('index.html').rstrip('/')
                if category == ALL_GALLERY_DIR or category.startswith(tuple(CATEGORY_NAMES.values()) + (_SAVED_ROOT,)):
                    self.send_response(302)
                    self.send_header('Location', '/view/gallery.html' + ('' if category == ALL_GALLERY_DIR else '?' + urlencode({'category': category})))
                    self.end_headers()
                    return
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
            if not self._local_request():
                return
            if urlsplit(self.path).path == '/api/knowledge/feedback':
                from .config import load_config
                from .knowledge_feedback import submit_feedback
                import secrets
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                    if not 0 < length <= _MAX_BODY:
                        raise ValueError('请求体过大或为空')
                    payload = json.loads(self.rfile.read(length).decode('utf-8'))
                    if not isinstance(payload, dict):
                        raise ValueError('需要JSON对象')
                    config_path = project_dir / 'config.yaml'
                    config = load_config(config_path)
                    token_path = config.data_dir / 'knowledge-feedback-token.txt'
                    if not token_path.is_file() or not secrets.compare_digest(str(payload.get('token') or ''), token_path.read_text(encoding='ascii').strip()):
                        self._json(403, {'error': '页面已过期，请重新生成群知识页面'})
                        return
                    result = submit_feedback(config_path, payload.get('scope',''), payload.get('kind'), payload.get('notes',''),
                                             item_key=payload.get('item_key'), message_id=payload.get('message_id'))
                    self._json(200, result)
                except (ValueError, TypeError, UnicodeDecodeError):
                    self._json(400, {'error': '反馈格式或来源不正确'})
                except Exception:
                    self._json(500, {'error': '反馈保存失败'})
                return
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
            tokens = accepted_tokens(project_dir) | {session_token}
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

        do_HEAD = do_GET

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


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='启动仅本机可访问的图片与报告服务')
    parser.add_argument('--project-dir', default='.')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    root = Path(args.project_dir).resolve()
    from .database_gallery import port_for
    serve(root, args.port if args.port is not None else port_for(root))

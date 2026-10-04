"""file_sync 端到端测试：本地 HTTP 服务模拟 WebDAV（PROPFIND/MKCOL/PUT），
scan_group 用假 call_action 验证入队，process_pending 走真实下载+上传链路。"""

import asyncio
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from qq_onebot_whitelist import file_sync
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.store import Store


# ---- 假 WebDAV 服务：记录请求，PUT 内容写到 tmp 目录 ----

@pytest.fixture()
def webdav(tmp_path):
    state = {"dirs": set(), "files": {}, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def _auth_ok(self):
            return self.headers.get('Authorization') in (None, 'Basic YWRtaW46MTIzNDU2')  # admin:123456

        def log_message(self, *args):
            pass

        def do_PROPFIND(self):
            state["requests"].append(('PROPFIND', self.path))
            if not self._auth_ok():
                self.send_response(401); self.end_headers(); return
            real = state["files"].get(self.path)
            if real is None:
                self.send_response(404); self.end_headers(); return
            body = f'<D:multistatus><D:response><D:propstat><D:prop><D:getcontentlength>{len(real)}</D:getcontentlength></D:prop></D:propstat></D:response></D:multistatus>'.encode()
            self.send_response(207)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_MKCOL(self):
            state["requests"].append(('MKCOL', self.path))
            if not self._auth_ok():
                self.send_response(401); self.end_headers(); return
            if self.path in state["dirs"]:
                self.send_response(405); self.end_headers(); return
            state["dirs"].add(self.path)
            self.send_response(201); self.end_headers()

        def do_PUT(self):
            state["requests"].append(('PUT', self.path))
            if not self._auth_ok():
                self.send_response(401); self.end_headers(); return
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b''
            state["files"][self.path] = body
            self.send_response(201); self.end_headers()

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {'url': f'http://admin:123456@127.0.0.1:{server.server_port}/dav',
           'url_noauth': f'http://127.0.0.1:{server.server_port}/dav',
           'state': state}
    server.shutdown()


@pytest.fixture()
def env(tmp_path, webdav):
    store = Store(tmp_path / 'bot.db')
    config = AppConfig(
        data_dir=tmp_path,
        file_sync_enabled=True,
        file_sync_webdav_url=webdav['url'],
        file_sync_remote_dir='QQ群文件',
        file_sync_staging_dir=tmp_path / 'staging',
        file_sync_max_file_gb=1,
    )
    return store, config, webdav


def fake_action(rows_by_group):
    """构造 call_action：返回 get_group_root_files 风格的目录树。"""
    async def call_action(action, params):
        gid = str(params.get('group_id'))
        tree = rows_by_group[gid]
        if action not in ('get_group_root_files', 'get_group_files_by_folder'):
            raise RuntimeError(f'unknown action {action}')
        if params.get('folder_id'):
            return {'status': 'ok', 'data': {'files': [], 'folders': []}}
        return {'status': 'ok', 'data': tree}
    return call_action


def test_enqueue_idempotent(env):
    store, config, webdav = env
    assert store.enqueue_file_upload(scope='1', file_id='F1', file_name='a.safetensors', file_size=10) is True
    assert store.enqueue_file_upload(scope='1', file_id='F1', file_name='a.safetensors', file_size=10) is False
    assert store.pending_file_uploads()[0]['file_name'] == 'a.safetensors'
    assert store.file_upload_status_counts() == {'pending': 1}


def test_scan_group_walks_tree_and_parses(env):
    store, config, webdav = env
    rows = {
        '1': {
            'files': [
                {'file_id': 'F1', 'file_name': 'model.safetensors', 'file_size': 5, 'uploaded_time': 1735689600, 'busid': 102},
            ],
            'folders': [{'folder_id': 'D1', 'folder_name': 'loras'}],
        }
    }
    seen = []
    total = asyncio.run(file_sync.scan_group(
        fake_action(rows), '1',
        on_file=lambda row: seen.append(row) or store.enqueue_file_upload(scope='1', **{
            'file_id': row['file_id'], 'file_name': row['file_name'],
            'file_size': row.get('file_size'), 'upload_time': str(row.get('upload_time')),
            'busid': row.get('busid')}),
    ))
    assert total == 1
    assert seen[0]['file_id'] == 'F1'
    assert seen[0]['busid'] == 102
    assert store.file_upload_status_counts() == {'pending': 1}


def test_process_pending_uploads_to_webdav(env, tmp_path):
    store, config, webdav = env
    content = b'model-bytes-here'
    # 本地"下载源"：HTTP 服务由 webdav fixture 兼任（PUT 目标与下载源共用端口无冲突，
    # 这里用 file:// 之外的思路——直接用本地 HTTP 服务再起一个端口太重，
    # 改为把下载 URL 指向 webdav 服务本身没有意义，因此 monkeypatch urlopen。
    import urllib.request
    from io import BytesIO

    class FakeResp(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        return FakeResp(content)

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        store.enqueue_file_upload(scope='88', file_id='F1', file_name='模型.safetensors',
                                  file_size=len(content), upload_time='1735689600', busid=102)

        async def fetch_url(gid, fid, busid=None):
            return 'http://download.example/file'

        stats = asyncio.run(file_sync.process_pending(store, config, fetch_url, limit=3))
    finally:
        urllib.request.urlopen = original

    assert stats['uploaded'] == 1
    counts = store.file_upload_status_counts()
    assert counts.get('uploaded') == 1
    # PUT 内容完整落到 WebDAV 服务
    puts = [(method, path) for method, path in webdav['state']['requests'] if method == 'PUT']
    assert len(puts) == 1
    assert next(iter(webdav['state']['files'].values())) == content
    # 暂存文件已清理
    assert not list((tmp_path / 'staging').rglob('*.safetensors'))


def test_process_pending_skips_oversize(env):
    store, config, webdav = env
    config.file_sync_max_file_gb = 0.000001  # ~1KB
    store.enqueue_file_upload(scope='1', file_id='BIG', file_name='big.ckpt', file_size=999999999)
    stats = asyncio.run(file_sync.process_pending(store, config, _noop_fetch, limit=3))
    assert stats['skipped'] == 1
    counts = store.file_upload_status_counts()
    assert counts.get('skipped') == 1


async def _noop_fetch(gid, fid, busid=None):
    raise AssertionError('超限文件不应触发取链接')


def test_retry_failed(env):
    store, config, webdav = env
    store.enqueue_file_upload(scope='1', file_id='F1', file_name='x.zip')
    row = store.pending_file_uploads()[0]
    store.mark_file_upload(row['id'], 'failed', error='boom')
    assert store.file_upload_status_counts() == {'failed': 1}
    assert store.retry_failed_file_uploads() == 1
    assert store.file_upload_status_counts() == {'pending': 1}


def test_remote_path_layout():
    path = file_sync.remote_path_for('QQ群文件', '模型群', '88', 'a.b模型.safetensors', '1735689600')
    assert path == 'QQ群文件/模型群/2025-01/a.b模型.safetensors'
    path2 = file_sync.remote_path_for('QQ群文件', '群<>?:名', '9', 'w?.json', None)
    assert '<' not in path2 and '?' not in path2


def test_sanitize_segment():
    assert file_sync.sanitize_segment('a<b>:"/\\|?*.zip') == 'a_b________.zip'
    assert file_sync.sanitize_segment('  ') == 'unnamed'

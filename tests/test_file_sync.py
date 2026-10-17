"""file_sync 端到端测试：本地 HTTP 服务模拟 WebDAV（PROPFIND/MKCOL/PUT），
scan_group 用假 call_action 验证入队，process_pending 走真实下载+上传链路。"""

import asyncio
import json
import sqlite3
import sys
import threading
import types
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


def test_scan_group_uses_folder_api_for_subfolders_and_stops_cycles():
    calls = []
    rows = []

    async def call_action(action, params):
        calls.append((action, dict(params)))
        if action == 'get_group_root_files':
            # Mirrors NapCat behavior: this endpoint ignores folder_id and repeats root.
            return {'status': 'ok', 'data': {
                'files': [{'file_id': 'root-file', 'file_name': 'root.txt', 'file_size': 1}],
                'folders': [{'folder_id': 'D1'}],
            }}
        if action == 'get_group_files_by_folder':
            assert params.get('folder_id') == 'D1'
            return {'status': 'ok', 'data': {
                'files': [{'file_id': 'child-file', 'file_name': 'child.txt', 'file_size': 2}],
                'folders': [{'folder_id': 'D1'}],
            }}
        pytest.fail(f'unexpected list action {action}')

    total = asyncio.run(file_sync.scan_group(call_action, '123', on_file=rows.append, file_count=10000))

    assert total == 2
    assert {row['file_id'] for row in rows} == {'root-file', 'child-file'}
    assert calls[0][0] == 'get_group_root_files'
    assert calls[0][1]['file_count'] == 10000
    folder_calls = [(action, params) for action, params in calls if params.get('folder_id')]
    assert folder_calls == [('get_group_files_by_folder', {'group_id': 123, 'folder_id': 'D1', 'file_count': 10000})]


def test_scan_group_reports_incomplete_tree_instead_of_returning_partial_results():
    async def call_action(action, params):
        if action == 'get_group_root_files':
            return {'status': 'ok', 'data': {'files': [], 'folders': [{'folder_id': 'D1'}]}}
        if action == 'get_group_files_by_folder':
            next_id = str(int(params['folder_id'][1:]) + 1)
            return {'status': 'ok', 'data': {'files': [], 'folders': [{'folder_id': f'D{next_id}'}]}}
        pytest.fail(f'unexpected list action {action}')

    with pytest.raises(RuntimeError, match='深度上限'):
        asyncio.run(file_sync.scan_group(call_action, '123', on_file=lambda _row: None, max_depth=2))


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


class FakeNapCatWebSocket:
    def __init__(self, handler):
        self.handler = handler
        self.sent = []
        self.responses = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def send(self, raw):
        request = json.loads(raw)
        self.sent.append(request)
        response = self.handler(request)
        if response is not None:
            response.setdefault('echo', request['echo'])
            self.responses.append(json.dumps(response))

    async def recv(self):
        return self.responses.pop(0)


def use_fake_napcat(monkeypatch, handler):
    import websockets
    fake = FakeNapCatWebSocket(handler)
    monkeypatch.setattr(websockets, 'connect', lambda *args, **kwargs: fake)
    return fake


def test_fetch_download_url_uses_live_file_id_without_scanning(monkeypatch):
    def respond(request):
        assert request['action'] == 'get_group_file_url'
        assert request['params'] == {'group_id': 123, 'file_id': 'live-id', 'busid': 5}
        return {'status': 'ok', 'data': {'url': 'https://download.invalid/live'}}

    fake = use_fake_napcat(monkeypatch, respond)
    url = file_sync.fetch_download_url_once('123', 'live-id', 5)

    assert url == 'https://download.invalid/live'
    assert [request['action'] for request in fake.sent] == ['get_group_file_url']


def test_fetch_download_url_recovers_stale_reference_by_unique_name_and_size(monkeypatch):
    def respond(request):
        action, params = request['action'], request['params']
        assert params['group_id'] == 123
        if action == 'get_group_file_url' and params['file_id'] == 'old-id':
            return {'status': 'failed', 'message': 'private stale cache details'}
        if action == 'get_group_root_files':
            assert params['file_count'] == 10000
            return {'status': 'ok', 'data': {'files': [
                {'file_id': 'fresh-id', 'file_name': 'same.pdf', 'file_size': 42, 'busid': 88},
                {'file_id': 'other', 'file_name': 'other.pdf', 'file_size': 42, 'busid': 99},
            ], 'folders': [{'folder_id': 'D1'}]}}
        if action == 'get_group_files_by_folder':
            assert params['folder_id'] == 'D1'
            return {'status': 'ok', 'data': {'files': [
                # Same file repeated in folder metadata is one candidate, not ambiguous.
                {'file_id': 'fresh-id', 'file_name': 'same.pdf', 'file_size': 42, 'busid': 88},
            ], 'folders': []}}
        if action == 'get_group_file_url' and params['file_id'] == 'fresh-id':
            assert params.get('busid') == 88
            return {'status': 'ok', 'data': {'url': 'https://download.invalid/fresh'}}
        pytest.fail(f'unexpected request action={action}')

    fake = use_fake_napcat(monkeypatch, respond)
    url = file_sync.fetch_download_url_once('123', 'old-id', 7,
                                           file_name='same.pdf', file_size=42)

    assert url == 'https://download.invalid/fresh'
    assert [r['action'] for r in fake.sent] == [
        'get_group_file_url', 'get_group_root_files', 'get_group_files_by_folder', 'get_group_file_url']
    assert fake.sent[0]['params']['busid'] == 7
    assert all(r['params']['group_id'] == 123 for r in fake.sent)
    assert fake.sent[-1]['params']['file_id'] == 'fresh-id'


def test_fetch_download_url_rejects_multiple_exact_matches(monkeypatch):
    def respond(request):
        if request['action'] == 'get_group_file_url':
            return {'status': 'failed'}
        if request['action'] == 'get_group_root_files':
            return {'status': 'ok', 'data': {'files': [
                {'file_id': 'one', 'file_name': 'same.pdf', 'file_size': 42},
                {'file_id': 'two', 'file_name': 'same.pdf', 'file_size': 42},
            ], 'folders': []}}
        pytest.fail('ambiguous match must not request a recovered URL')

    use_fake_napcat(monkeypatch, respond)
    with pytest.raises(file_sync.AmbiguousFileReference):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)


def test_fetch_download_url_requires_name_and_size_both_to_match(monkeypatch):
    def respond(request):
        if request['action'] == 'get_group_file_url':
            return {'status': 'failed'}
        if request['action'] == 'get_group_root_files':
            return {'status': 'ok', 'data': {'files': [
                {'file_id': 'name-only', 'file_name': 'same.pdf', 'file_size': 41},
                {'file_id': 'size-only', 'file_name': 'different.pdf', 'file_size': 42},
            ], 'folders': []}}
        pytest.fail('non-exact match must not request a recovered URL')

    use_fake_napcat(monkeypatch, respond)
    with pytest.raises(file_sync.FileReferenceUnavailable):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)


def test_fetch_download_url_does_not_accept_unique_match_from_truncated_scan(monkeypatch):
    requested_ids = []

    def respond(request):
        action, params = request['action'], request['params']
        if action == 'get_group_file_url':
            requested_ids.append(params['file_id'])
            if params['file_id'] == 'expired':
                return {'status': 'failed'}
            pytest.fail('a partial listing cannot prove uniqueness')
        if action == 'get_group_root_files':
            return {'status': 'ok', 'data': {'files': [
                {'file_id': 'apparently-unique', 'file_name': 'same.pdf', 'file_size': 42},
            ], 'folders': [{'folder_id': 'D1'}]}}
        if action == 'get_group_files_by_folder':
            current = int(params['folder_id'][1:])
            return {'status': 'ok', 'data': {'files': [], 'folders': [{'folder_id': f'D{current + 1}'}]}}
        pytest.fail(f'unexpected list action {action}')

    use_fake_napcat(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='安全扫描'):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)
    assert requested_ids == ['expired']


def test_fetch_download_url_does_not_accept_failed_listing_with_partial_files(monkeypatch):
    requested_ids = []

    def respond(request):
        action, params = request['action'], request['params']
        if action == 'get_group_file_url':
            requested_ids.append(params['file_id'])
            if params['file_id'] == 'expired':
                return {'status': 'failed'}
            pytest.fail('failed listing cannot authorize requesting a recovered ID')
        return {'status': 'failed', 'data': {'files': [
            {'file_id': 'partial-match', 'file_name': 'same.pdf', 'file_size': 42},
        ], 'folders': []}}

    use_fake_napcat(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='安全扫描'):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)
    assert requested_ids == ['expired']


@pytest.mark.parametrize('envelope', ['async_status', 'has_more', 'has_more_int', 'next_cursor', 'total_count'])
def test_fetch_download_url_rejects_explicitly_paginated_listing(monkeypatch, envelope):
    requested_ids = []

    def respond(request):
        action, params = request['action'], request['params']
        if action == 'get_group_file_url':
            requested_ids.append(params['file_id'])
            if params['file_id'] == 'expired':
                return {'status': 'failed'}
            pytest.fail('explicitly paginated result cannot authorize URL recovery')
        page = {'files': [{'file_id': 'apparently-unique', 'file_name': 'same.pdf', 'file_size': 42}],
                'folders': []}
        if envelope == 'async_status':
            return {'status': 'async', 'data': page}
        if envelope == 'has_more':
            return {'status': 'ok', 'data': {**page, 'has_more': True}}
        if envelope == 'has_more_int':
            return {'status': 'ok', 'data': {**page, 'hasMore': 1}}
        if envelope == 'next_cursor':
            return {'status': 'ok', 'data': {'data': {**page, 'nextCursor': 'next-page'}}}
        return {'status': 'ok', 'data': {'data': {**page, 'totalCount': 2}}}

    use_fake_napcat(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='安全扫描'):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)
    assert requested_ids == ['expired']


def test_fetch_download_url_rejects_page_at_file_count_limit(monkeypatch):
    requested_ids = []

    def respond(request):
        action, params = request['action'], request['params']
        if action == 'get_group_file_url':
            requested_ids.append(params['file_id'])
            if params['file_id'] == 'expired':
                return {'status': 'failed'}
            pytest.fail('a full page cannot establish uniqueness')
        if action == 'get_group_root_files':
            return {'status': 'ok', 'data': {'files': [
                {'file_id': f'id-{i}', 'file_name': 'same.pdf', 'file_size': 42}
                for i in range(10000)
            ], 'folders': []}}
        pytest.fail(f'unexpected list action {action}')

    fake = use_fake_napcat(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='安全扫描'):
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf', file_size=42)
    assert requested_ids == ['expired']
    assert fake.sent[1]['params']['file_count'] == 10000


def test_fetch_download_url_without_complete_metadata_does_not_scan(monkeypatch):
    fake = use_fake_napcat(monkeypatch, lambda _request: {'status': 'failed', 'message': 'signed-url-secret'})

    with pytest.raises(RuntimeError) as exc:
        file_sync.fetch_download_url_once('123', 'expired', file_name='same.pdf')

    assert 'signed-url-secret' not in str(exc.value)
    assert [r['action'] for r in fake.sent] == ['get_group_file_url']

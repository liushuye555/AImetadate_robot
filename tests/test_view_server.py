"""本地图库服务（view_server）测试：静态访问、token 鉴权、导出任务。"""

import json
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from qq_onebot_whitelist import view_server

SCHEMA = """CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
    format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
    ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
    deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT, sha256 TEXT,
    merged_into INTEGER, saved_category TEXT, prompt_key TEXT, context_reason TEXT,
    bound_prompt TEXT, stego_state TEXT)"""


def _make_project(tmp_path):
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / 'bot.db')
    conn.execute(SCHEMA)
    img = tmp_path / 'img.png'
    Image.new('RGB', (640, 640)).save(img)
    conn.execute(
        "INSERT INTO images (scope, user_id, seen_at, format, width, height, retention_reason, "
        "kept_path, ai_source, has_ai_metadata, sha256) "
        "VALUES ('group:1', '100', '2026-09-01 10:00:00', 'PNG', 640, 640, 'ai_metadata', ?, "
        "'A1111', 1, 'sha-1')", (str(img),))
    conn.commit()
    conn.close()
    view = data / 'view'
    (view / '01_AI元数据_ComfyUI').mkdir(parents=True)
    (view / '01_AI元数据_ComfyUI' / 'index.html').write_text('<html>gallery</html>', encoding='utf-8')
    (view / 'index.html').write_text('<html>hub</html>', encoding='utf-8')
    (data / 'view-build-state.json').write_text(json.dumps({
        'version': 22, 'build_token': 'tok123', 'build_token_history': ['tok123'],
    }), encoding='utf-8')
    return tmp_path


def _server(project_dir):
    httpd = view_server.make_server(project_dir, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{port}'


def _post(base, payload):
    req = Request(base + '/api/export', data=json.dumps(payload).encode('utf-8'),
                  headers={'Content-Type': 'application/json'})
    return json.loads(urlopen(req).read())


def test_serves_static_pages_and_blocks_traversal(tmp_path):
    project = _make_project(tmp_path)
    httpd, base = _server(project)
    try:
        # 中文目录按 URL 编码访问
        with urlopen(base + '/view/' + quote('01_AI元数据_ComfyUI') + '/index.html') as resp:
            assert b'gallery' in resp.read()
        # 根路径跳转到视图入口
        with urlopen(base + '/') as resp:
            assert b'hub' in resp.read()
        # 目录穿越被拒绝（../ 与 %5C 反斜杠两种路径）
        with pytest.raises(HTTPError) as ei:
            urlopen(base + '/view/../bot.db')
        assert ei.value.code == 403
        with pytest.raises(HTTPError) as ei:
            urlopen(base + '/view/%2e%2e%5cbot.db')
        assert ei.value.code in (403, 404)
    finally:
        httpd.shutdown()


def test_export_requires_valid_token(tmp_path):
    project = _make_project(tmp_path)
    httpd, base = _server(project)
    try:
        with pytest.raises(HTTPError) as ei:
            _post(base, {'token': 'wrong', 'dry_run': True})
        assert ei.value.code == 403
        assert '过期' in json.loads(ei.value.read())['error']
    finally:
        httpd.shutdown()


def test_export_dry_run_job_completes_with_summary(tmp_path):
    project = _make_project(tmp_path)
    httpd, base = _server(project)
    try:
        resp = _post(base, {'token': 'tok123', 'dry_run': True, 'min_side': 512})
        assert resp['status'] == 'running'
        status = {'status': 'running'}
        for _ in range(200):
            status = json.loads(urlopen(base + '/api/export/status').read())
            if status['status'] != 'running':
                break
            time.sleep(0.1)
        assert status['status'] == 'done'
        assert status['summary']['dry_run'] is True
        assert status['summary']['counts']['selected'] == 1
        assert status['params']['min_side'] == 512
    finally:
        httpd.shutdown()


def test_param_validation():
    argv, err = view_server._validate_params({'out': 'bad name!', 'dry_run': True})
    assert err and '目录名' in err
    _, err = view_server._validate_params({'orientation': 'diagonal'})
    assert err
    _, err = view_server._validate_params({'since': '2026/01/01'})
    assert err
    _, err = view_server._validate_params({'min_side': 'abc'})
    assert err
    _, err = view_server._validate_params({'limit': 0})
    assert err
    argv, err = view_server._validate_params({'user': '100', 'min_side': 768, 'keyword': ' shiroko '})
    assert err is None
    assert argv[argv.index('--user') + 1] == '100'
    assert argv[argv.index('--min-side') + 1] == '768'
    assert argv[argv.index('--keyword') + 1] == 'shiroko'


def test_out_dir_param_validation():
    argv, err = view_server._validate_params({'out_dir': 'D:\\datasets\\lora'})
    assert err is None
    assert argv[argv.index('--out-dir') + 1] == 'D:\\datasets\\lora'
    _, err = view_server._validate_params({'out_dir': 'relative/path'})
    assert err and '绝对路径' in err
    argv, err = view_server._validate_params({'out_dir': '"E:\\data\\set"'})
    assert err is None
    assert 'E:\\data\\set' in argv


def test_export_to_absolute_folder_via_api(tmp_path):
    project = _make_project(tmp_path)
    target = tmp_path.parent / 'api_out_dir_dest_test'  # 项目目录之外
    httpd, base = _server(project)
    try:
        _post(base, {'token': 'tok123', 'out_dir': str(target)})
        status = {'status': 'running'}
        for _ in range(200):
            status = json.loads(urlopen(base + '/api/export/status').read())
            if status['status'] != 'running':
                break
            time.sleep(0.1)
        assert status['status'] == 'done'
        assert status['summary']['counts']['exported'] == 1
        assert status['summary']['out'] == str(target)
        assert len(list(target.glob('*.png'))) == 1
    finally:
        httpd.shutdown()

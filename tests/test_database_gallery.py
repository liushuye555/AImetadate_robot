"""Live catalogue, report compatibility, file serving and matching exports."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from qq_onebot_whitelist.gallery_store import facets, query_images
from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist.view_server import make_server


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'data').mkdir()
    Store(tmp_path / 'data' / 'bot.db')
    (tmp_path / 'config.yaml').write_text('view_server:\n  port: 3789\n', encoding='utf-8')
    return tmp_path


def add(project, **values):
    path = project / 'data' / 'images' / 'ai' / (str(values.get('user_id', '100')) + '.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        Image.new('RGB', (800, 1200), 'navy').save(path)
    row = dict(scope='group:1', user_id='100', seen_at='2026-10-24 00:00:00',
               width=800, height=1200, size=path.stat().st_size, format='PNG',
               retention_reason='ai_metadata', ai_source='ComfyUI', kept_path=str(path),
               sha256='', text_excerpt='蓝色 portrait', bound_prompt='workflow')
    row.update(values)
    with sqlite3.connect(project / 'data' / 'bot.db') as conn:
        cur = conn.execute('INSERT INTO images (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
        return cur.lastrowid


@contextmanager
def server(project):
    httpd = make_server(project, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{httpd.server_port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def get(base, route):
    with urlopen(base + route) as response:
        return json.load(response)


def test_filter_before_dedup_live_updates_and_stable_pagination(project):
    first = add(project, sha256='same', user_id='100')
    add(project, sha256='same', user_id='200', scope='group:2')
    add(project, retention_reason='candidate', sha256='candidate')
    for i in range(4):
        add(project, sha256=f'other{i}', user_id='300')
    assert query_images(project, {})['total'] == 5
    assert query_images(project, {'user': '100'})['items'][0]['id'] == first
    one = query_images(project, {'page_size': 2})
    two = query_images(project, {'page_size': 2, 'page': 2})
    assert not ({r['id'] for r in one['items']} & {r['id'] for r in two['items']})
    assert one['has_more']
    with server(project) as base:
        old = get(base, '/api/gallery/images')['total']
        new = add(project, sha256='new')
        result = get(base, '/api/gallery/images')
        assert result['total'] == old + 1 and result['items'][0]['id'] == new
        assert not (project / 'data' / 'view').exists()


def test_context_memberships_merged_rows_and_rejected_discussions(project):
    primary = add(project, sha256='restored', retention_reason='xiaofanqie_obfuscated', deobfuscated=1)
    merged = add(project, sha256='restored', kept_path=None, merged_into=primary, context_reason='positive_feedback')
    selected = add(project, retention_reason='params_discussion', sha256='selected')
    rejected = add(project, retention_reason='params_discussion', sha256='rejected')
    with sqlite3.connect(project / 'data' / 'bot.db') as conn:
        conn.execute("INSERT INTO image_discussions (image_id,scope,status,reason,context_text,evidence_json,updated_at) VALUES (?,'group:1','selected','','完整讨论原文','[]','2026-10-24')", (selected,))
        conn.execute("INSERT INTO image_discussions (image_id,scope,status,reason,context_text,evidence_json,updated_at) VALUES (?,'group:1','rejected','','拒绝内容','[]','2026-10-24')", (rejected,))
    result = query_images(project, {'category': '02_群友好评'})
    assert result['total'] == 1
    assert result['items'][0]['id'] == merged
    assert result['items'][0]['url'] == f'/media/images/{primary}'
    assert result['items'][0]['deobfuscated'] == 1  # inherit restored-file mask after a merge
    params = query_images(project, {'category': '03_参数讨论'})
    assert params['total'] == 1 and params['items'][0]['discussion_text'] == '完整讨论原文'
    assert 'kept_path' not in params['items'][0] and 'raw_json' not in params['items'][0]
    categories = {c['name']: c['count'] for c in facets(project)['categories']}
    assert categories['02_群友好评'] == 1 and categories['03_参数讨论'] == 1


def test_media_thumbnails_cache_revalidation_missing_and_escape(project, tmp_path):
    image = add(project)
    outside = tmp_path.parent / 'outside-gallery.png'
    Image.new('RGB', (1, 1)).save(outside)
    external = add(project, kept_path=str(outside))
    invalid = add(project, kept_path=str(project / 'config.yaml'))
    missing = add(project, kept_path=str(project / 'missing.png'))
    try:
        with server(project) as base:
            url = f'/media/images/{image}/thumbnail'
            with urlopen(base + url) as response:
                etag = response.headers['ETag']
                import io
                with Image.open(io.BytesIO(response.read())) as thumb:
                    assert max(thumb.size) <= 480
            with pytest.raises(HTTPError) as exc:
                urlopen(Request(base + url, headers={'If-None-Match': etag}))
            assert exc.value.code == 304
            with urlopen(Request(base + f'/media/images/{image}', method='HEAD')) as response:
                assert response.read() == b'' and int(response.headers['Content-Length']) > 0
            for bad in (external, invalid, missing, 99999):
                with pytest.raises(HTTPError) as exc:
                    urlopen(base + f'/media/images/{bad}')
                assert exc.value.code == 404
            Image.new('RGB', (200, 100), 'red').save(project / 'data/images/ai/100.png')
            with urlopen(base + url) as response:
                assert response.headers['ETag'] != etag
            for route in ('/media/images/../../config.yaml', '/api/gallery/images?page=-1',
                          '/api/gallery/images?sort=id%3BDROP', '/api/gallery/images?user=1&user=2'):
                with pytest.raises(HTTPError) as exc:
                    urlopen(base + route)
                assert exc.value.code in (400, 404)
    finally:
        outside.unlink(missing_ok=True)


def test_build_and_report_list_use_database_without_creating_links(project, monkeypatch, capsys):
    from qq_onebot_whitelist.build_image_view import build_view
    from qq_onebot_whitelist import control
    add(project, sha256='one')
    view = project / 'data' / 'view'
    view.mkdir()
    wallpaper = view / 'wallpaper.jpg'
    Image.new('RGB', (24, 24), 'navy').save(wallpaper)
    original_wallpaper = wallpaper.read_bytes()
    (view / 'knowledge.html').write_text('existing knowledge', encoding='utf-8')
    legacy = view / '02_群友好评' / 'old.png'
    legacy.parent.mkdir()
    legacy.write_bytes(b'historical reference')
    import os
    monkeypatch.setattr(os, 'link', lambda *_a, **_k: pytest.fail('routine view must not create hardlinks'))
    counts = build_view(project)
    assert counts['00_全部'] == 1
    assert legacy.exists() and (view / 'knowledge.html').read_text() == 'existing knowledge'
    assert '127.0.0.1:3789' in (view / 'index.html').read_text(encoding='utf-8')
    assert 'location.search' in (view / 'gallery.html').read_text(encoding='utf-8')
    assert 'wallpaper-ready' in (view / 'index.html').read_text(encoding='utf-8')
    assert 'url("/view/wallpaper.jpg")' in (view / 'gallery.html').read_text(encoding='utf-8')
    assert wallpaper.read_bytes() == original_wallpaper
    assert len(list(view.rglob('*.png'))) == 1
    monkeypatch.setattr(control, 'REPO_ROOT', project)
    assert control.cmd_view_list(argparse.Namespace()) == 0
    output = capsys.readouterr().out.strip().splitlines()[-1]
    categories = json.loads(output)['categories']
    assert all(c['url'].startswith('gallery.html') for c in categories)
    assert any(c['name'] == '01_AI元数据_ComfyUI' and c['count'] == 1 for c in categories)
    assert not any(c['name'] == '02_群友好评' for c in categories)  # stale directory isn't a DB category
    with server(project) as base:
        for route in ('/view/', '/view/gallery.html'):
            with urlopen(base + route) as response:
                page = response.read().decode('utf-8')
                assert 'wallpaper-ready' in page and 'wallpaper.jpg' in page
        assert urlopen(base + '/view/wallpaper.jpg').read() == original_wallpaper


def test_report_navigation_and_export_match_gallery_selection(project):
    from qq_onebot_whitelist.export_dataset import export_dataset
    add(project, scope='group:1', sha256='same', user_id='100')
    add(project, scope='group:2', sha256='same', user_id='200')
    add(project, scope='group:1', sha256='other', user_id='300')
    add(project, scope='group:1', sha256='candidate', retention_reason='candidate')
    query = {'scope': 'group:1', 'orientation': 'portrait', 'keyword': '蓝色', 'sort': 'oldest'}
    selected = query_images(project, query)
    exported = export_dataset(project, gallery_query=query, dry_run=True)
    assert exported['manifest']['counts']['selected'] == selected['total'] == 2
    copied = export_dataset(project, gallery_query=query, captions=False, out='gallery-test')
    assert copied['manifest']['counts']['exported'] == 2
    assert all(p.stat().st_nlink == 1 for p in Path(copied['out_dir']).glob('*.png'))
    with server(project) as base:
        with urlopen(base + '/view/02_%E7%BE%A4%E5%8F%8B%E5%A5%BD%E8%AF%84/index.html') as response:
            assert 'gallery.html?category=' in response.url
        root = urlopen(base + '/view/').read().decode('utf-8')
        for name in ('knowledge.html', 'glossary.html', 'knowledge-summary.html', 'knowledge-files.html', 'files.html', 'resources.html'):
            assert name in root
        assert 'gallery.html?category=' in root and 'gallery.html%3F' not in root
        meta = get(base, '/api/gallery/meta')
        request = Request(base + '/api/export', data=json.dumps({'token': meta['token'], 'gallery_query': query, 'dry_run': True}).encode(), headers={'Content-Type': 'application/json'})
        assert json.load(urlopen(request))['status'] == 'running'
        import time
        for _ in range(100):
            status = get(base, '/api/export/status')
            if status['status'] != 'running':
                break
            time.sleep(.05)
        assert status['status'] == 'done'
        assert status['summary']['counts']['selected'] == 2
        from http.client import HTTPConnection
        from urllib.parse import urlsplit
        for headers in ({'Origin': 'https://example.invalid'}, {'Host': 'example.invalid'}):
            # Bypass the machine's HTTP proxy when testing a deliberately non-local Host.
            connection = HTTPConnection('127.0.0.1', urlsplit(base).port)
            connection.request('GET', '/api/gallery/meta', headers=headers)
            assert connection.getresponse().status == 403
            connection.close()


def test_frontend_exports_and_pages_the_applied_query():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is only needed for the frontend state regression check')
    script = Path(__file__).with_name('gallery_frontend_harness.cjs')
    gallery = Path(__file__).parents[1] / 'qq_onebot_whitelist' / 'gallery.html'
    subprocess.run([node, str(script), str(gallery)], check=True, capture_output=True, text=True, timeout=10)


def test_lightbox_reads_original_prompt_and_merged_file_without_exposing_paths(project):
    from PIL.PngImagePlugin import PngInfo
    image = add(project, sha256='original', text_excerpt='truncated')
    prompt = 'a detailed original prompt ' * 40
    meta = PngInfo()
    meta.add_text('parameters', prompt + '\nNegative prompt: blurry\nSteps: 20, Sampler: Euler')
    Image.new('RGB', (800, 1200), 'navy').save(project / 'data/images/ai/100.png', pnginfo=meta)
    merged = add(project, sha256='original', kept_path=None, merged_into=image,
                 context_reason='positive_feedback')
    outside = add(project, kept_path=str(project.parent / 'outside.png'))
    with server(project) as base:
        for selected in (image, merged):
            detail = get(base, f'/api/gallery/images/{selected}')
            assert detail == {'filename': '100.png', 'prompt': prompt.strip(), 'nickname': ''}
            assert 'truncated' not in detail['prompt']
        for selected in (outside, 999999):
            with pytest.raises(HTTPError) as exc:
                get(base, f'/api/gallery/images/{selected}')
            assert exc.value.code == 404

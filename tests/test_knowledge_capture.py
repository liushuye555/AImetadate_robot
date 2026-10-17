import asyncio
import json
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import yaml

from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.knowledge import automatic_tick
from qq_onebot_whitelist.knowledge_capture import capture_tick, enqueue_event_files
from qq_onebot_whitelist.knowledge_store import KnowledgeDB, LOCAL_TZ
from qq_onebot_whitelist.onebot import handle_event
from qq_onebot_whitelist.store import Store


def config_file(tmp_path, *, mode='save_all', files_enabled=True, collection_files=True,
                group_enabled=True, knowledge_enabled=True, blocked=False):
    data = tmp_path / 'data'
    raw = {
        'storage': {'data_dir': str(data)},
        'collection': {'groups': {'group:123': {'files': collection_files}}},
        'knowledge': {
            'enabled': knowledge_enabled,
            'groups': {'group:123': {
                'enabled': group_enabled,
                'files': {'enabled': files_enabled, 'mode': mode},
                'extraction': {'enabled': False},
                'glossary': {'enabled': False},
                'summary': {'enabled': False},
            }},
        },
    }
    if blocked:
        raw['listen'] = {'blocked_groups': ['123']}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding='utf-8')
    return path


def file_event(file_id='fid-1', *, message_id=1, name='manual.pdf', size=12):
    return {
        'post_type': 'message', 'message_type': 'group', 'group_id': '123',
        'user_id': '42', 'message_id': message_id,
        'message': [{'type': 'file', 'data': {'file_id': file_id, 'name': name, 'size': size}}],
    }


def assets(db):
    with db.conn() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM assets ORDER BY file_id')]


def test_event_file_is_queued_without_ai_and_duplicate_does_not_overwrite_saved(tmp_path):
    path = config_file(tmp_path)
    config = load_config(path)
    db = KnowledgeDB(config.data_dir / 'knowledge.db')
    event = file_event()
    assert enqueue_event_files(config, 'group:123', event, 9) == 1
    queued = assets(db)[0]
    assert queued['status'] == 'pending'
    source = json.loads(queued['source_json'])
    assert source['message_id'] == 9 and 'url' not in source

    saved_path = tmp_path / 'already-saved.pdf'
    saved_path.write_bytes(b'kept')
    import hashlib
    source['file_size'] = 4
    db.asset(source, {'status': 'saved', 'path': str(saved_path), 'size': 4,
                      'sha256': hashlib.sha256(b'kept').hexdigest()})
    assert enqueue_event_files(config, 'group:123', event, 99) == 0
    saved = assets(db)[0]
    assert saved['status'] == 'saved' and saved['path'] == str(saved_path)


def test_group_upload_notice_is_recorded_and_queued_without_sending(tmp_path):
    path = config_file(tmp_path)
    config = load_config(path)
    store = Store(config.data_dir / 'bot.db')
    event = {
        'post_type': 'notice', 'notice_type': 'group_upload', 'group_id': '123',
        'user_id': '42', 'file': {'id': 'notice-fid', 'name': 'upload.zip', 'size': 25},
    }
    assert asyncio.run(handle_event(None, event, config, store, path)) is False
    rows = assets(KnowledgeDB(config.data_dir / 'knowledge.db'))
    assert len(rows) == 1
    assert rows[0]['file_id'] == 'notice-fid' and rows[0]['status'] == 'pending'


def test_repeated_caption_reply_does_not_skip_file_capture(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    config = load_config(path)
    store = Store(config.data_dir / 'bot.db')
    monkeypatch.setattr('qq_onebot_whitelist.onebot.echo_reply_text', lambda *a: 'caption')

    async def fake_reply(*args):
        pass

    monkeypatch.setattr('qq_onebot_whitelist.onebot.send_reply', fake_reply)
    assert asyncio.run(handle_event(None, file_event(), config, store, path)) is True
    assert assets(KnowledgeDB(config.data_dir / 'knowledge.db'))[0]['status'] == 'pending'


@pytest.mark.parametrize('options', [
    {'knowledge_enabled': False},
    {'group_enabled': False},
    {'files_enabled': False},
    {'collection_files': False},
    {'blocked': True},
    {'mode': 'high_value'},
])
def test_capture_enqueue_gates_leave_no_database(tmp_path, options):
    path = config_file(tmp_path, **options)
    config = load_config(path)
    assert enqueue_event_files(config, 'group:123', file_event(), 1) == 0
    assert not (config.data_dir / 'knowledge.db').exists()


def test_save_all_cannot_be_inherited_from_defaults(tmp_path):
    from qq_onebot_whitelist.knowledge_config import profile_for
    path = config_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['defaults'] = {'files': {'mode': 'save_all'}}
    del raw['knowledge']['groups']['group:123']['files']['mode']
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    config = load_config(path)
    assert profile_for(config, 'group:123').settings['files']['mode'] == 'high_value'
    assert enqueue_event_files(config, 'group:123', file_event(), 1) == 0
    assert not (config.data_dir / 'knowledge.db').exists()


def test_capture_tick_obeys_failed_cooldown_and_prioritizes_fresh_pending(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    config = load_config(path)
    db = KnowledgeDB(config.data_dir / 'knowledge.db')
    now = datetime.now(LOCAL_TZ)
    fresh_failed = {'scope': 'group:123', 'file_id': 'failed-fresh', 'message_id': 1,
                    'file_name': 'recent.pdf', 'file_size': 1}
    old_failed = {'scope': 'group:123', 'file_id': 'failed-old', 'message_id': 2,
                  'file_name': 'retry.pdf', 'file_size': 1}
    db.queue_asset(fresh_failed)
    db.queue_asset(old_failed)
    with db.conn() as conn:
        conn.execute("UPDATE assets SET status='failed',last_attempt_at=? WHERE file_id=?",
                     (now.isoformat(), 'failed-fresh'))
        conn.execute("UPDATE assets SET status='failed',last_attempt_at=? WHERE file_id=?",
                     ((now - timedelta(minutes=11)).isoformat(), 'failed-old'))

    attempted_ids = []

    def save_selected(config_path, target_db, records, result, *, capture=False):
        assert capture is True
        for source in records[0]['files']:
            attempted_ids.append(source['file_id'])
            saved_path = tmp_path / (source['file_id'] + '.pdf')
            saved_path.write_bytes(b'captured locally')
            import hashlib
            target_db.asset(source, {'status': 'saved', 'path': str(saved_path),
                                     'size': saved_path.stat().st_size,
                                     'sha256': hashlib.sha256(saved_path.read_bytes()).hexdigest()})

    monkeypatch.setattr('qq_onebot_whitelist.knowledge.retain_selected_files', save_selected)
    monkeypatch.setattr('qq_onebot_whitelist.knowledge.write_view', lambda *args: None)
    assert capture_tick(path)['attempted'] == 1  # only the eligible, old failure
    assert attempted_ids == ['failed-old']

    new_source = {'scope': 'group:123', 'file_id': 'new-pending', 'message_id': 3,
                  'file_name': 'new.pdf', 'file_size': 1}
    db.queue_asset(new_source)
    with db.conn() as conn:
        conn.execute("UPDATE assets SET status='failed',last_attempt_at=? WHERE file_id=?",
                     ((now - timedelta(minutes=11)).isoformat(), 'failed-old'))
    attempts_before = len(attempted_ids)
    result = capture_tick(path)
    assert result['attempted'] == 2
    assert attempted_ids[attempts_before:] == ['new-pending', 'failed-old']
    rows = {row['file_id']: row for row in assets(db)}
    assert rows['failed-fresh']['status'] == 'failed'  # recent failure remains in cooldown
    assert rows['new-pending']['status'] == rows['failed-old']['status'] == 'saved'
    assert (tmp_path / 'new-pending.pdf').read_bytes() == b'captured locally'


def test_save_all_files_only_automatic_tick_does_not_call_ai(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    monkeypatch.setattr('qq_onebot_whitelist.knowledge.LLMConfig.from_env',
                        lambda *args, **kwargs: pytest.fail('save_all files-only tick must not read AI credentials'))
    assert automatic_tick(path, request=lambda *a: pytest.fail('save_all files-only tick must not call AI')) == []


def test_collected_file_downloads_to_local_archive_before_any_ai_selection(tmp_path, monkeypatch):
    from qq_onebot_whitelist.collection import collect_event

    payload = b'local upload fixture\n'

    class Download(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Download)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = config_file(tmp_path)
        config = load_config(path)
        store = Store(config.data_dir / 'bot.db')
        monkeypatch.setattr('qq_onebot_whitelist.file_sync.fetch_download_url_once',
                            lambda *a, **k: f'http://127.0.0.1:{server.server_port}/fixture')
        monkeypatch.setattr('qq_onebot_whitelist.knowledge.analyze',
                            lambda *a, **k: pytest.fail('capture must precede AI'))
        assert collect_event(store, file_event(name='notes.md', size=len(payload)), config)
        assert capture_tick(path)['attempted'] == 1
        db = KnowledgeDB(config.data_dir / 'knowledge.db')
        row = assets(db)[0]
        assert row['status'] == 'saved'
        from pathlib import Path
        archived = Path(row['path'])
        assert archived.is_relative_to(config.data_dir / 'knowledge-files' / '123')
        assert archived.read_bytes() == payload
        assert db.asset_saved('group:123', 'fid-1')
        assert capture_tick(path)['attempted'] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_capture_disabled_during_fetch_stays_pending_and_resumes(tmp_path, monkeypatch):
    path = config_file(tmp_path)
    config = load_config(path)
    db = KnowledgeDB(config.data_dir / 'knowledge.db')
    enqueue_event_files(config, 'group:123', file_event(name='notes.md', size=4), 1)

    def disable_during_fetch(*args, **kwargs):
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        raw['knowledge']['groups']['group:123']['files']['mode'] = 'review'
        path.write_text(yaml.safe_dump(raw), encoding='utf-8')
        return 'http://127.0.0.1/not-requested'

    monkeypatch.setattr('qq_onebot_whitelist.file_sync.fetch_download_url_once', disable_during_fetch)
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_files.download_to_staging',
                        lambda *a, **k: pytest.fail('disabled download must stop'))
    assert capture_tick(path)['attempted'] == 1
    assert assets(db)[0]['status'] == 'pending'
    assert capture_tick(path)['attempted'] == 0

    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['knowledge']['groups']['group:123']['files']['mode'] = 'save_all'
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    monkeypatch.setattr('qq_onebot_whitelist.file_sync.fetch_download_url_once', lambda *a, **k: 'fixture')
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_files.download_to_staging',
                        lambda url, stage, **k: stage.write_bytes(b'kept'))
    assert capture_tick(path)['attempted'] == 1
    assert db.asset_saved('group:123', 'fid-1')

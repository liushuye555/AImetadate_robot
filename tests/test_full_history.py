"""SnowLuma complete-history pagination contracts."""

import asyncio
import json
import sqlite3

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist import gateway, full_history


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)


def _message(seq, message_id, *, time=None, text=None):
    return {
        'post_type': 'message',
        'message_type': 'group',
        'group_id': 42,
        'user_id': 7,
        'message_seq': seq,
        'message_id': message_id,
        'time': time if time is not None else seq,
        'message': text if text is not None else f'msg-{seq}',
    }


def _run_backfill(monkeypatch, tmp_path, responses, *, state=None, count=10, seeded=()):
    config = AppConfig(data_dir=tmp_path, onebot_provider='snowluma')
    store = Store(tmp_path / 'bot.db')
    for event in seeded:
        store.record_message(
            scope='group:42', user_id=str(event['user_id']),
            text=str(event['message']), raw=event,
        )
    ws = FakeWS()
    calls = []
    saves = []
    pages = iter(responses)

    async def fake_call(actual_ws, action, params, **kwargs):
        calls.append((actual_ws, action, dict(params)))
        return {'data': {'messages': next(pages)}}

    monkeypatch.setattr(gateway, 'call', fake_call)

    async def scenario():
        checkpoint = state if state is not None else {
            'status': 'running',
            'pages': 0,
            'imported': 0,
            'anchor': None,
            'oldest_time': None,
            'newest_time': None,
        }

        def save():
            saves.append(dict(checkpoint))

        result = await full_history.backfill_group(
            config, store, ws, 42, checkpoint, save, count=count, delay=0,
        )
        return result

    result = asyncio.run(scenario())
    return result, store, calls, saves, ws


def test_snow_pagination_uses_message_id_and_min_sequence_anchor(monkeypatch, tmp_path):
    rows = [
        _message(30, 30, time=300),
        _message(10, -10, time=100),  # Negative IDs are valid anchors.
        _message(20, 20, time=200),
    ]
    result, store, calls, saves, ws = _run_backfill(
        monkeypatch, tmp_path, [rows, []], count=25,
    )

    assert calls[0][1] == 'get_group_msg_history'
    assert calls[0][2]['count'] == 25
    assert 'message_id' in calls[0][2]
    assert 'message_seq' not in calls[0][2]
    assert calls[1][2]['message_id'] == -10
    records = store.recent_records('group:42')
    assert [record['text'] for record in records] == ['msg-10', 'msg-20', 'msg-30']
    assert result['status'] == 'available_end'
    assert result['anchor'] == -10
    assert result['pages'] == 1
    assert saves  # A successful page is checkpointed before the empty page.
    assert saves[0]['anchor'] == -10
    assert ws.sent == []


def test_old_duplicate_page_still_advances_and_overlapping_boundary_is_deduped(monkeypatch, tmp_path):
    first_page = [_message(4, 4), _message(3, 3)]
    # Entire first response is already in storage; it must not be mistaken for end.
    result, store, calls, saves, ws = _run_backfill(
        monkeypatch,
        tmp_path,
        [first_page, [_message(3, 3), _message(2, 2)], []],
        seeded=first_page,
    )
    assert calls[1][2]['message_id'] == 3
    assert calls[2][2]['message_id'] == 2
    assert result['status'] == 'available_end'
    assert result['imported'] == 1
    assert len(store.recent_records('group:42')) == 3
    assert {row['text'] for row in store.recent_records('group:42')} == {
        'msg-2', 'msg-3', 'msg-4',
    }
    assert len(saves) == 3  # Two page checkpoints plus the no-progress terminal checkpoint.
    assert ws.sent == []


def test_repeated_anchor_with_messages_stops_as_no_progress(monkeypatch, tmp_path):
    rows = [_message(8, 8), _message(7, 7)]
    result, store, calls, saves, ws = _run_backfill(
        monkeypatch, tmp_path, [rows, rows],
    )

    assert len(calls) == 2
    assert result['status'] == 'no_progress'
    assert result['anchor'] == 7
    assert result['imported'] == 2
    assert len(store.recent_records('group:42')) == 2
    assert len(saves) == 2  # Successful page checkpoint and terminal no-progress checkpoint.
    assert ws.sent == []


def test_resume_starts_from_saved_anchor_and_only_archives_raw_messages(monkeypatch, tmp_path):
    state = {
        'status': 'running',
        'pages': 5,
        'imported': 12,
        'anchor': '-900',
        'oldest_time': 100,
        'newest_time': 200,
    }
    rows = [_message(6, -901, text='旧的 /保存命令')]
    result, store, calls, saves, ws = _run_backfill(
        monkeypatch, tmp_path, [rows, []], state=state,
    )

    assert calls[0][2]['message_id'] == -900
    assert 'message_seq' not in calls[0][2]
    assert result['anchor'] == -901
    assert result['pages'] == 6
    assert result['imported'] == 13
    record = store.recent_records('group:42')[0]
    assert record['text'] == '旧的 /保存命令'
    with store._conn() as conn:
        raw_json = conn.execute(
            'SELECT raw_json FROM messages WHERE scope = ? AND message_key = ?',
            ('group:42', '-901'),
        ).fetchone()[0]
    assert json.loads(raw_json)['message_id'] == -901
    assert saves[0]['anchor'] == -901
    assert ws.sent == []


def test_history_page_uses_original_dates_for_messages_and_report_links(tmp_path):
    store = Store(tmp_path / 'bot.db')
    event = _message(1, 123, time=1609459200, text='old https://example.com/model')
    assert store.record_history_page(scope='group:42', events=[event, event]) == 1
    assert store.record_history_page(scope='group:42', events=[event]) == 0
    with store._conn() as conn:
        assert conn.execute('SELECT seen_at FROM messages').fetchall() == [('2021-01-01 00:00:00',)]
        assert conn.execute('SELECT seen_at FROM links').fetchall() == [('2021-01-01 00:00:00',)]
    assert store.recent_link_records(since='2026-01-01 00:00:00') == []


def test_history_page_rolls_back_if_later_message_is_invalid(tmp_path):
    import pytest
    store = Store(tmp_path / 'bot.db')
    with pytest.raises(ValueError, match='identity'):
        store.record_history_page(scope='group:42', events=[_message(1, 123), {'message': 'no id'}])
    assert store.recent_records('group:42') == []


def test_recent_views_keep_live_records_ahead_of_later_imported_old_history(tmp_path):
    store = Store(tmp_path / 'bot.db')
    live = _message(500, 500, text='live https://example.com/new')
    store.record_message(scope='group:42', user_id='7', text=live['message'], raw=live)
    store.record_history_page(scope='group:42', events=[
        _message(1, 1, time=1609459200, text='old https://example.com/old')])
    assert store.recent_records('group:42', limit=1)[0]['text'] == live['message']
    assert store.recent_records_all(limit=1)[0]['text'] == live['message']
    assert store.recent_links(limit=1) == ['https://example.com/new']
    assert store.recent_link_records(limit=1)[0]['url'] == 'https://example.com/new'


class FakeConnection:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *args):
        return False


def _install_run_gateway_mocks(monkeypatch, group_pages):
    ws = FakeWS()
    calls = []
    pages = {gid: list(responses) for gid, responses in group_pages.items()}

    monkeypatch.setattr(gateway, 'connect', lambda *args, **kwargs: FakeConnection(ws))

    async def fake_call(actual_ws, action, params=None, **kwargs):
        params = params or {}
        calls.append((action, dict(params)))
        if action == 'get_login_info':
            return {'data': {'user_id': 'bot-qq'}}
        if action == 'get_group_list':
            return {'data': [{'group_id': gid, 'group_name': f'group-{gid}'}
                             for gid in [1, 2, 3]]}
        if action == 'get_group_msg_history':
            return {'data': {'messages': pages[params['group_id']].pop(0)}}
        raise AssertionError(f'unexpected action: {action}')

    monkeypatch.setattr(gateway, 'call', fake_call)
    return calls, ws


def test_run_archives_all_unblocked_groups_with_concurrent_workers(monkeypatch, tmp_path):
    config = AppConfig(
        data_dir=tmp_path,
        onebot_provider='snowluma',
        blocked_groups={'1'},
    )
    calls, ws = _install_run_gateway_mocks(monkeypatch, {
        2: [[{**_message(20, 200, text='group two'), 'group_id': 2}], []],
        3: [[{**_message(30, 300, text='group three'), 'group_id': 3}], []],
    })

    result = asyncio.run(full_history.run(
        config, tmp_path / 'state.json', count=20, delay=0, concurrency=2,
    ))

    assert result['selected_groups'] == ['2', '3']
    assert set(result['groups']) == {'2', '3'}
    assert result['groups']['2']['status'] == 'available_end'
    assert result['groups']['3']['status'] == 'available_end'
    assert result['status'] == 'finished'
    assert all(call[1].get('group_id') != 1 for call in calls if call[0] == 'get_group_msg_history')
    history_group_ids = {
        str(params['group_id']) for action, params in calls
        if action == 'get_group_msg_history'
    }
    assert history_group_ids == {'2', '3'}
    store = Store(tmp_path / 'bot.db')
    assert [row['text'] for row in store.recent_records('group:2')] == ['group two']
    assert [row['text'] for row in store.recent_records('group:3')] == ['group three']
    assert result['groups']['2']['pages'] == result['groups']['3']['pages'] == 1
    assert result['groups']['2']['anchor'] == 200
    assert result['groups']['3']['anchor'] == 300
    assert ws.sent == []


def test_run_marks_empty_first_page_unverified_and_needs_attention(monkeypatch, tmp_path):
    config = AppConfig(
        data_dir=tmp_path,
        onebot_provider='snowluma',
        blocked_groups={'2', '3'},
    )
    _install_run_gateway_mocks(monkeypatch, {1: [[]]})

    result = asyncio.run(full_history.run(
        config, tmp_path / 'state.json', count=20, delay=0, concurrency=1,
    ))

    assert result['groups']['1']['status'] == 'empty_unverified'
    assert result['selected_groups'] == ['1']
    assert result['status'] == 'finished_with_limits'


def test_run_resumes_terminal_group_checkpoints_without_requerying(monkeypatch, tmp_path):
    config = AppConfig(data_dir=tmp_path, onebot_provider='snowluma')
    calls, _ws = _install_run_gateway_mocks(monkeypatch, {})
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({
        'identity': {'provider': 'snowluma', 'account': 'bot-qq'},
        'groups': {
            '1': {'status': 'available_end', 'pages': 3, 'imported': 10, 'anchor': 100},
            '2': {'status': 'no_progress', 'pages': 4, 'imported': 20, 'anchor': 200},
            '3': {'status': 'empty_unverified', 'pages': 0, 'imported': 0, 'anchor': 0},
        },
    }), encoding='utf-8')

    result = asyncio.run(full_history.run(
        config, state_path, count=20, delay=0, concurrency=2,
    ))

    assert result['groups']['1']['status'] == 'available_end'
    assert result['groups']['2']['status'] == 'no_progress'
    assert result['groups']['3']['status'] == 'empty_unverified'
    assert result['status'] == 'finished_with_limits'
    assert not any(action == 'get_group_msg_history' for action, _params in calls)


def test_locked_history_page_retries_before_checkpointing(monkeypatch, tmp_path):
    config = AppConfig(data_dir=tmp_path, onebot_provider='snowluma')
    store = Store(tmp_path / 'bot.db')
    ws = FakeWS()
    rows = [_message(11, -11, text='saved once')]
    responses = iter([rows, []])
    calls = []
    saves = []
    sleeps = []
    real_record_page = store.record_history_page
    attempts = 0

    async def fake_call(actual_ws, action, params, **kwargs):
        calls.append(dict(params))
        return {'data': {'messages': next(responses)}}

    async def no_sleep(seconds):
        sleeps.append(seconds)

    def record_with_transient_lock(*, scope, events):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError('database is locked')
        return real_record_page(scope=scope, events=events)

    monkeypatch.setattr(gateway, 'call', fake_call)
    monkeypatch.setattr(full_history.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(store, 'record_history_page', record_with_transient_lock)
    state = {
        'status': 'running', 'pages': 0, 'imported': 0, 'anchor': None,
        'oldest_time': None, 'newest_time': None,
    }

    result = asyncio.run(full_history.backfill_group(
        config, store, ws, 42, state, lambda: saves.append(dict(state)),
        count=10, delay=0,
    ))

    assert attempts == 2
    assert sleeps == [1, 0]
    assert len(calls) == 2
    assert calls[0]['message_id'] == 0
    assert calls[1]['message_id'] == -11
    assert any(snapshot['status'] == 'retrying' and snapshot['pages'] == 0
               and snapshot['anchor'] is None for snapshot in saves)
    success_checkpoint = next(snapshot for snapshot in saves if snapshot.get('anchor') == -11)
    assert success_checkpoint['status'] == 'running'
    assert success_checkpoint['pages'] == 1
    assert success_checkpoint['imported'] == 1
    assert result['status'] == 'available_end'
    assert result['anchor'] == -11
    assert len(store.recent_records('group:42')) == 1
    assert store.recent_records('group:42')[0]['text'] == 'saved once'
    assert ws.sent == []

import json
import sqlite3

from qq_onebot_whitelist.knowledge_store import read_records


def _message(conn, *, scope, user_id, text, key, raw=None):
    conn.execute(
        'INSERT INTO messages(scope,user_id,text,raw_json,seen_at,links_json,message_key) VALUES(?,?,?,?,?,?,?)',
        (scope, user_id, text, json.dumps(raw or {}, ensure_ascii=False), '2026-10-01 10:00:00', '[]', key),
    )
    return int(conn.execute('SELECT last_insert_rowid()').fetchone()[0])


def test_read_records_returns_scope_scoped_anonymous_speaker_keys(tmp_path):
    db = tmp_path / 'bot.db'
    with sqlite3.connect(db) as conn:
        conn.execute('''CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, text TEXT,
            raw_json TEXT, seen_at TEXT, links_json TEXT, message_key TEXT
        )''')
        first = _message(conn, scope='group:1', user_id='alice-private-uid', text='first', key='a')
        same_author = _message(conn, scope='group:1', user_id='alice-private-uid', text='second', key='b')
        other_author = _message(conn, scope='group:1', user_id='bob-private-uid', text='third', key='c')
        other_group = _message(conn, scope='group:2', user_id='alice-private-uid', text='fourth', key='d')
        quoted = _message(
            conn, scope='group:1', user_id=None, text='reply', key='e',
            raw={'message': [{'type': 'reply', 'data': {'id': 'b'}}]},
        )
        unknown = _message(conn, scope='group:1', user_id='', text='unknown', key='f')

    group_one = read_records(db, 'group:1', limit=20)
    by_id = {record['id']: record for record in group_one}
    assert by_id[first]['actor_key']
    assert len(by_id[first]['actor_key']) == 12
    assert by_id[first]['actor_key'] == by_id[same_author]['actor_key']
    assert by_id[first]['actor_key'] != by_id[other_author]['actor_key']
    assert by_id[first]['actor_key'] != by_id[quoted]['actor_key']
    assert by_id[quoted]['quoted_id'] == same_author
    assert by_id[quoted]['quoted_text'] == 'second'
    assert by_id[quoted]['quoted_actor_key'] == by_id[first]['actor_key']
    assert by_id[unknown]['actor_key'] is None
    assert by_id[unknown]['quoted_actor_key'] is None

    group_two = read_records(db, 'group:2', limit=20)
    assert group_two[0]['actor_key'] != by_id[first]['actor_key']
    assert all('user_id' not in record for record in [*group_one, *group_two])
    serialized = json.dumps([*group_one, *group_two], ensure_ascii=False)
    assert 'alice-private-uid' not in serialized
    assert 'bob-private-uid' not in serialized

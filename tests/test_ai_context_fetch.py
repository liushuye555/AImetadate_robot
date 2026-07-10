import json
import sqlite3

from qq_onebot_whitelist.ai_context_analyze import fetch_records
from qq_onebot_whitelist.store import Store


def test_fetch_records_reads_sender_and_reply_context(tmp_path):
    db = tmp_path / 'bot.db'
    Store(db)
    conn = sqlite3.connect(db)
    conn.execute(
        'INSERT INTO messages (scope,user_id,text,links_json,raw_json,message_key) VALUES (?,?,?,?,?,?)',
        ('group:1', 'u1', '原消息', '[]', json.dumps({'message_id': 10, 'sender': {'nickname': '甲'}}), '10'),
    )
    conn.execute(
        'INSERT INTO messages (scope,user_id,text,links_json,raw_json,message_key) VALUES (?,?,?,?,?,?)',
        ('group:1', 'u2', '回复内容', '[]', json.dumps({'message_id': 11, 'sender': {'card': '乙'}, 'message': [{'type': 'reply', 'data': {'id': 10}}]}), '11'),
    )
    conn.commit()
    conn.close()

    records = fetch_records(db, scope='group:1')

    assert records[0]['nickname'] == '甲'
    assert records[1]['card'] == '乙'
    assert records[1]['quoted_text'] == '原消息'


def test_fetch_records_resolves_reply_from_previous_batch(tmp_path):
    db = tmp_path / 'bot.db'
    Store(db)
    conn = sqlite3.connect(db)
    conn.execute(
        'INSERT INTO messages (scope,user_id,text,links_json,raw_json,message_key) VALUES (?,?,?,?,?,?)',
        ('group:1', 'u1', '上一批提示词', '[]', json.dumps({'message_id': 20}), '20'),
    )
    first_id = conn.execute('SELECT id FROM messages WHERE message_key = ?', ('20',)).fetchone()[0]
    conn.execute(
        'INSERT INTO messages (scope,user_id,text,links_json,raw_json,message_key) VALUES (?,?,?,?,?,?)',
        ('group:1', 'u2', '这个怎么出的', '[]', json.dumps({'message_id': 21, 'message': [{'type': 'reply', 'data': {'id': 20}}]}), '21'),
    )
    conn.commit()
    conn.close()

    records = fetch_records(db, scope='group:1', after_id=first_id)

    assert records[0]['quoted_text'] == '上一批提示词'

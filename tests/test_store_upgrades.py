"""采集存储升级：群名缓存表、转发子事件去重键、撤回审计、线程本地连接。"""

import json
import sqlite3
import threading

from qq_onebot_whitelist import onebot
from qq_onebot_whitelist.build_image_view import group_name_map_from_conn
from qq_onebot_whitelist.store import Store


def test_group_names_upsert_and_rename(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_message(scope='group:123', user_id='u', text='hi',
                         raw={'message_id': 1, 'group_name': '测试群'})
    mapping = store.group_name_map()
    assert mapping['123'] == '测试群'
    assert mapping['group:123'] == '测试群'

    # 群改名后取最新
    store.record_message(scope='group:123', user_id='u', text='hi',
                         raw={'message_id': 2, 'group_name': '新名字'})
    assert store.group_name_map()['123'] == '新名字'
    # 私聊消息不带群名，不影响缓存
    store.record_message(scope='private:u', user_id='u', text='yo',
                         raw={'message_id': 3})
    assert store.group_name_map()['123'] == '新名字'


def test_group_names_backfill_from_legacy_db(tmp_path):
    """旧库（无 group_names 表）初始化时从 raw_json 一次性回填。"""
    db = tmp_path / 'legacy.db'
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "scope TEXT, user_id TEXT, text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)")
    conn.execute("INSERT INTO messages (scope, raw_json) VALUES ('group:55', ?)",
                 (json.dumps({'group_id': 55, 'group_name': '旧群名'}),))
    conn.commit()
    conn.close()

    store = Store(db)
    mapping = store.group_name_map()
    assert mapping['55'] == '旧群名'
    assert mapping['group:55'] == '旧群名'

    # 视图构建侧同一条缓存路径
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        assert group_name_map_from_conn(conn)['55'] == '旧群名'
    finally:
        conn.close()


def test_forward_sub_event_stable_dedup_key(tmp_path):
    """转发子事件有稳定 message_id：重复展开不再重复入库。"""
    store = Store(tmp_path / 'bot.db')

    event = {'group_id': 1}
    for _ in range(2):  # 同一条转发重复展开
        sub_event = onebot.forward_sub_event(event, 'abc', {'user_id': 'u', 'message': []}, 0)
        store.record_message(scope='group:1', user_id='u', text='x', raw=sub_event)
    assert onebot.forward_sub_event(event, 'abc', {'user_id': 'u', 'message': []}, 0)['message_id'] == 'fwd-abc-0'

    conn = sqlite3.connect(store.path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE message_key = 'fwd-abc-0'").fetchone()[0]
    finally:
        conn.close()
    assert count == 1

    # 节点自带真实 id 时优先用真实 id
    real = onebot.forward_sub_event(event, 'abc', {'user_id': 'u', 'message': [], 'message_id': 999}, 3)
    assert real['message_id'] == 999


def test_group_recall_audit(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_group_recall(scope='group:1', group_id='1',
                              message_id='42', user_id='u1', operator_id='admin')
    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            'SELECT scope, group_id, message_id, user_id, operator_id FROM group_recalls').fetchone()
    finally:
        conn.close()
    assert row == ('group:1', '1', '42', 'u1', 'admin')


def test_store_shared_across_threads(tmp_path):
    """同一 Store 可安全跨线程使用（线程本地连接互不串扰）。"""
    store = Store(tmp_path / 'bot.db')
    store.record_message(scope='group:1', user_id='a', text='main', raw={'message_id': 1})
    seen = {}

    def worker():
        store.record_message(scope='group:1', user_id='b', text='thread', raw={'message_id': 2})
        seen['count'] = len(store.recent_records('group:1', limit=10))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen['count'] == 2

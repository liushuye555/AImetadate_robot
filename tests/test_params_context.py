"""History evidence must belong to the image, and remain reviewable."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from qq_onebot_whitelist.params_context import _record, audit_params, build_image_context, substantive
from qq_onebot_whitelist.store import Store


def add(store, key, actor, text='', *, image=False, reply=None, stamp=1000, scope='group:1'):
    segments = []
    if image:
        segments.append({'type': 'image', 'data': {'url': 'https://example.test/image.png'}})
    if reply is not None:
        segments.append({'type': 'reply', 'data': {'id': str(reply)}})
    raw = {'message_id': key, 'time': stamp, 'message': segments}
    store.record_message(scope=scope, user_id=actor, text=text, raw=raw)
    return store.message_row_id(scope, raw)


def test_original_author_and_alternative_answer_stay_separate(tmp_path):
    store = Store(tmp_path / 'bot.db')
    question = add(store, 100, 'asker', '用的是什么底模和lora吗？')
    answer = add(store, 101, 'owner', 'krea2 turbo int8', stamp=1010)
    source = add(store, 102, 'owner', image=True, stamp=1020)
    alternative = add(store, 103, 'other', '就是k2的。FP8', reply=100, stamp=1030)
    later = add(store, 104, 'owner', 'lora就这个，加不加无所谓吧', stamp=1040)
    add(store, 105, 'unrelated', '训练LoRA的权重为0.8', stamp=1045)

    result = build_image_context(store, 'group:1', source)
    assert result['status'] == 'selected'
    assert result['evidence_ids'] == [question, answer, source, alternative, later]
    assert '成员2 · 讨论\nkrea2 turbo int8' in result['text']
    assert '成员3 · 讨论，引用 #' in result['text']
    assert '训练LoRA的权重为0.8' not in result['text']


@pytest.mark.parametrize('text', ['lora？', '被lora训练词污染了吧', '正在思考，LoRA训练进度为10'])
def test_questions_speculation_and_processing_are_not_results(text):
    assert not substantive(text)


def test_source_anchor_no_cross_scope_or_latest_fallback(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'owner', image=True)
    add(store, 2, 'other', 'LoRA权重设置0.8', stamp=1010)
    add(store, 3, 'owner', 'LoRA权重设置0.8', stamp=1020, scope='group:2')
    assert build_image_context(store, 'group:1', source)['status'] == 'pending'
    assert build_image_context(store, 'group:2', source)['evidence_ids'] == []
    assert build_image_context(store, 'group:1', None)['evidence_ids'] == []


def test_same_author_new_image_ends_prior_image_discussion(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'owner', image=True)
    add(store, 2, 'owner', image=True, stamp=1010)
    add(store, 3, 'owner', 'LoRA权重设置0.8', stamp=1020)
    assert build_image_context(store, 'group:1', source)['status'] == 'pending'


def test_explicit_reply_to_another_image_overrides_same_author_proximity(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'alice', image=True)
    add(store, 2, 'bob', image=True, stamp=1010)
    add(store, 3, 'alice', 'LoRA权重0.8，采样28步', reply=2, stamp=1020)
    assert build_image_context(store, 'group:1', source)['status'] == 'pending'


def test_question_quoting_another_picture_cannot_pollute_evidence(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'alice', image=True)
    unrelated = add(store, 2, 'bob', '另外一张图的sampler用什么？', reply=999, stamp=1010)
    valid = add(store, 3, 'alice', 'Krea2 turbo使用int8', stamp=1020)
    add(store, 4, 'carol', '实测FP8速度更快', reply=2, stamp=1030)
    result = build_image_context(store, 'group:1', source)
    assert result['evidence_ids'] == [source, valid]
    assert unrelated not in result['evidence_ids']


def test_explicit_source_quote_can_resolve_old_parameter_post(tmp_path):
    store = Store(tmp_path / 'bot.db')
    parent = add(store, 1, 'author', 'LoRA权重设置0.8', stamp=1000)
    source = add(store, 2, 'owner', image=True, reply=1, stamp=5000)
    result = build_image_context(store, 'group:1', source)
    assert result['status'] == 'selected'
    assert result['evidence_ids'] == [parent, source]


def test_busy_group_reply_is_not_cut_off_after_twelve_messages(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'owner', image=True)
    for i in range(2, 35):
        add(store, i, 'other', '聊天', stamp=1000+i)
    answer = add(store, 35, 'owner', 'Krea2 turbo使用int8', reply=1, stamp=1040)
    result = build_image_context(store, 'group:1', source)
    assert result['status'] == 'selected'
    assert result['evidence_ids'] == [source, answer]


def test_audit_uses_canonical_source_and_explicit_ids_can_inspect_candidates(tmp_path):
    store = Store(tmp_path / 'data' / 'bot.db')
    source = add(store, 1, 'owner', 'Krea2 turbo使用int8', image=True)
    store.record_image(scope='group:1', user_id='owner', result={'retention_reason': 'candidate'},
                       raw={'message_db_id': source})
    with store._conn() as conn:
        iid = conn.execute('SELECT id FROM images').fetchone()[0]
        conn.execute('UPDATE images SET raw_json=?', ('{}',))
        conn.commit()
    assert audit_params(tmp_path)['checked'] == 0
    result = audit_params(tmp_path, image_ids=[iid])
    assert result['selected'] == 1
    assert source in result['samples'][0]['evidence_ids']


def test_mixed_event_and_database_timestamps_use_utc():
    epoch = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc).timestamp()
    database = _record((1, '1', 'owner', '', '2026-10-13 08:00:00', '{}'))
    event = _record((2, '2', 'owner', '', '2026-10-13 08:00:00', json.dumps({'time': epoch})))
    assert database['timestamp'] == event['timestamp'] == epoch


def test_out_of_order_future_question_does_not_become_prior_evidence(tmp_path):
    store = Store(tmp_path / 'bot.db')
    source = add(store, 1, 'owner', image=True, stamp=1000)
    add(store, 2, 'asker', '使用什么底模和LoRA吗？', stamp=1100)
    answer = add(store, 3, 'owner', 'Krea2 turbo使用int8', stamp=1010)
    assert build_image_context(store, 'group:1', source)['evidence_ids'] == [source, answer]


def test_dry_audit_does_not_create_decision_table(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    path = data / 'bot.db'
    store = Store(path)
    source = add(store, 1, 'owner', 'LoRA权重设置0.8', image=True)
    store.record_image(scope='group:1', user_id='owner',
                       result={'retention_reason': 'params_discussion'}, raw={'message_db_id': source})
    with store._conn() as conn:
        conn.execute('DROP TABLE image_discussions')
        conn.commit()
    result = audit_params(tmp_path)
    assert result['selected'] == result['checked'] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='image_discussions'").fetchone() is None


def test_audit_preserves_manual_rejection_and_retention(tmp_path):
    store = Store(tmp_path / 'data' / 'bot.db')
    source = add(store, 1, 'owner', 'LoRA权重设置0.8', image=True)
    store.record_image(scope='group:1', user_id='owner',
                       result={'retention_reason': 'params_discussion', 'kept_path': 'original.png'},
                       raw={'message_db_id': source})
    with store._conn() as conn:
        iid = conn.execute('SELECT id FROM images').fetchone()[0]
    store.set_image_discussion(iid, 'rejected', '歌单封面', manual=True)
    result = audit_params(tmp_path, apply=True)
    assert result['manual_preserved'] == result['rejected'] == 1
    with store._conn() as conn:
        assert conn.execute('SELECT retention_reason,kept_path FROM images').fetchone() == ('params_discussion', 'original.png')

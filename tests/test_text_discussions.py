"""Future text discussions are independent of picture collection."""
from datetime import datetime, timedelta
import json

import pytest
import yaml

from qq_onebot_whitelist.knowledge import _material, automatic_tick, validate_result, with_context
from qq_onebot_whitelist.knowledge_store import KnowledgeDB, LOCAL_TZ, read_records
from qq_onebot_whitelist.llm_summary import LLMConfig
from qq_onebot_whitelist.store import Store


MODEL = LLMConfig('https://example.invalid/v1', 'test', 'test-model')
SCOPE = 'group:123'


def message(store, key, actor, text, *, reply=None, scope=SCOPE):
    segments = [{'type': 'text', 'data': {'text': text}}]
    if reply is not None:
        segments.append({'type': 'reply', 'data': {'id': str(reply)}})
    raw = {'message_id': key, 'time': 1791781200, 'message': segments}
    store.record_message(scope=scope, user_id=actor, text=text, raw=raw)
    return store.message_row_id(scope, raw)


def configure(tmp_path):
    data = tmp_path / 'data'
    store = Store(data / 'bot.db')
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'storage': {'data_dir': str(data)}, 'knowledge': {
        'enabled': True, 'groups': {SCOPE: {'enabled': True, 'extraction': {'enabled': True},
        'min_new_messages': 1, 'interval_minutes': 1, 'batch_size': 100}}}}, allow_unicode=True), encoding='utf-8')
    return config, store


def test_live_answer_to_old_text_thread_is_extracted_without_images(tmp_path):
    config, store = configure(tmp_path)
    question = message(store, 1, 'alice', 'Krea2用INT8和FP8有区别吗？')
    prior = message(store, 2, 'bob', '我的设置用INT8，LoRA权重0.8', reply=1)
    for i in range(3, 33):
        message(store, i, 'chat', '闲聊')
    assert automatic_tick(config, request=lambda *args: pytest.fail('activation only'), model=MODEL) == []
    db = KnowledgeDB(store.path.parent / 'knowledge.db')
    with db.conn() as conn:
        conn.execute('UPDATE cursors SET updated_at=?', ((datetime.now(LOCAL_TZ)-timedelta(minutes=2)).isoformat(),))
    answer = message(store, 33, 'carol', '我实测FP8更快，LoRA为0.6；不是上一位的INT8设置', reply=2)

    def request(messages, model):
        material = json.loads(messages[1]['content'])['messages']
        by_id = {r['id']: r for r in material}
        assert by_id[question]['context_only'] and by_id[prior]['context_only']
        assert not by_id[answer]['context_only']
        assert by_id[prior]['speaker'] != by_id[answer]['speaker']
        assert by_id[answer]['quoted_speaker'] == by_id[prior]['speaker']
        assert all(r['files'] == [] and r['segments'] in (['text'], ['text', 'reply']) for r in material)
        assert '纯文字讨论也可独立成为高价值知识' in messages[0]['content']
        return {'summary': [], 'terms': [], 'items': [{
            'title': 'Krea2量化设置对比', 'summary': '成员分别报告INT8和FP8，LoRA不同；速度为群友实测反馈，不能混为同一设置。',
            'kind': '对比', 'topic': 'AI绘图', 'value': 'high', 'evidence_state': 'verified',
            'evidence_ids': [question, prior, answer], 'file_ids': []}]}, 80

    result = automatic_tick(config, request=request, model=MODEL)[0]
    assert result['status'] == 'completed' and result['input_count'] == 1
    assert result['start_id'] == result['end_id'] == answer
    assert len(db.items(SCOPE)) == 1 and db.items('group:999') == []
    with store._conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM images').fetchone()[0] == 0
    page = (store.path.parent / 'view' / 'knowledge.html').read_text(encoding='utf-8')
    assert 'Krea2量化设置对比' in page and '文字讨论可独立收录' in page
    assert '精选讨论' in page and '待确认讨论' in page and 'data-value="high"' in page
    assert '成员1' in page and '成员2' in page and '成员3' in page


def test_reply_context_is_bounded_and_cycles_do_not_duplicate(tmp_path):
    store = Store(tmp_path / 'bot.db')
    for i in range(1, 42):
        message(store, i, 'alice', '讨论'+str(i), reply=i-1 if i>1 else None)
    for i in range(42, 102):
        message(store, i, 'other', '闲聊')
    source = message(store, 102, 'bob', '这次已经验证了', reply=41)
    records = read_records(store.path, SCOPE, after_id=source-1, limit=1)
    enriched = with_context(store.path, SCOPE, source-1, records)
    context_ids = {r['id'] for r in enriched if r.get('context_only')}
    assert {41, 40, 39, 38} <= context_ids and 37 not in context_ids
    assert len(context_ids) <= 40
    assert len({r['id'] for r in enriched}) == len(enriched)
    # Corrupt/cyclic history cannot trigger unbounded source loading.
    records[0]['quoted_id'] = source
    assert len(with_context(store.path, SCOPE, source-1, records)) <= 41


def test_context_is_scoped_and_old_only_evidence_cannot_make_new_item(tmp_path):
    store = Store(tmp_path / 'bot.db')
    old = message(store, 1, 'alice', '问题')
    current = message(store, 2, 'bob', '回答', reply=1)
    other = message(store, 1, 'alice', '别群', scope='group:999')
    enriched = with_context(store.path, SCOPE, old, read_records(store.path, SCOPE, after_id=old))
    assert {r['id'] for r in enriched} == {old, current}
    with pytest.raises(ValueError, match='其他群'):
        with_context(store.path, SCOPE, 0, read_records(store.path, 'group:999'))
    with pytest.raises(ValueError, match='旧上下文'):
        validate_result({'summary': [{'text': '旧结论', 'evidence_ids': [old]}]}, enriched)
    assert other not in {r['id'] for r in enriched}


def test_material_speakers_are_local_labels_not_ids_or_hashes(tmp_path):
    store = Store(tmp_path / 'bot.db')
    message(store, 1, '9876543210', 'LoRA权重0.8')
    message(store, 2, '9876543211', 'LoRA权重0.6', reply=1)
    records = read_records(store.path, SCOPE)
    material = _material(records)
    assert material[0]['speaker'] == material[1]['quoted_speaker'] == '成员1'
    assert material[1]['speaker'] == '成员2'
    serialized = json.dumps(material)
    assert '9876543210' not in serialized and '9876543211' not in serialized
    assert all(r['actor_key'] not in serialized for r in records)
    for r in records:
        r['actor_key'] = None
    assert all(r['speaker'] == '成员未知' for r in _material(records))

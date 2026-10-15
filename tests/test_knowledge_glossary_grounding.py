import json

from qq_onebot_whitelist.knowledge import validate_result
from qq_onebot_whitelist.knowledge_grounding import effective_term
from qq_onebot_whitelist.knowledge_store import KnowledgeDB


def rows(second_time='2026-10-15T12:40:00+08:00', second_text='跑图在这里指生成图像'):
    return [dict(id=1, text='跑图就是生成图像', time='2026-10-15T12:00:00+08:00', files=[]),
            dict(id=2, text=second_text, time=second_time, files=[])]


def result(records, *, definitions=True):
    term = dict(term='跑图', meaning='本群指生成图像', evidence_ids=[1, 2])
    if definitions:
        term['definition_evidence'] = [dict(message_id=r['id'], quote=r['text']) for r in records]
    return validate_result({'terms': [term]}, records)


def save(tmp_path, value):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    db.finish('test', 'group:123', value, 0, extraction=False, glossary=True)
    return db


def test_mentions_do_not_enable_meaning(tmp_path):
    records = rows()
    assert save(tmp_path, result(records, definitions=False)).terms('group:123')[0]['status'] == 'candidate'


def test_quoted_definitions_need_independent_time_and_text(tmp_path):
    for index, records in enumerate([
        rows('2026-10-15T12:01:00+08:00'),
        rows(second_text='跑图就是生成图像'),
        rows(second_time=None),
        rows(second_time='2026-10-15T12:40:00'),
    ]):
        db = save(tmp_path / str(index), result(records))
        assert db.terms('group:123')[0]['status'] == 'candidate'


def test_distinct_definitions_can_enable_and_manual_meanings_stay_authoritative(tmp_path):
    db = save(tmp_path, result(rows()))
    assert db.terms('group:123')[0]['status'] == 'active'
    db.set_term('group:123', '跑图', '人工解释')
    db.finish('another', 'group:123', result(rows()), 0, extraction=False, glossary=True)
    active = [t for t in db.terms('group:123') if t['status'] == 'active']
    assert len(active) == 1 and active[0]['meaning'] == '人工解释'


def test_fabricated_or_foreign_quote_cannot_enable(tmp_path):
    records = rows()
    value = {'terms': [dict(term='跑图', meaning='本群指生成图像', evidence_ids=[1, 2],
                           definition_evidence=[dict(message_id=1, quote='跑图就是生成图像'),
                                                dict(message_id=2, quote='跑图就是绘画'),
                                                dict(message_id=999, quote=records[1]['text'])])]}
    db = save(tmp_path, validate_result(value, records))
    assert db.terms('group:123')[0]['status'] == 'candidate'


def test_legacy_mention_hashes_are_not_reused_as_confirmed_definitions(tmp_path):
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    with db.conn() as conn:
        conn.execute('INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)',
                     ('old', 'group:123', 'LoRA', '旧释义', '[1,2]', 'active', json.dumps(['a' * 64, 'b' * 64]), 'ai'))
    assert db.terms('group:123')[0]['status'] == 'candidate'
    assert effective_term(dict(status='active', origin='user', contexts_json='[]'))['status'] == 'active'


def test_review_receives_recheckable_definition_quotes(tmp_path):
    records = rows()
    preliminary = result(records)
    assert preliminary['terms'][0]['definition_evidence'] == [
        {'message_id': r['id'], 'quote': r['text']} for r in records]
    reviewed = validate_result(preliminary, records)
    assert reviewed['terms'][0]['supporting_contexts'] == preliminary['terms'][0]['supporting_contexts']
    assert save(tmp_path, reviewed).terms('group:123')[0]['status'] == 'active'


def test_repeated_source_with_different_excerpts_does_not_enable_meaning(tmp_path):
    records = rows()
    for record in records:
        record['text'] = '跑图就是生成图像。这里跑图指生成图像。'
    value = {'terms': [dict(term='跑图', meaning='生成图像', evidence_ids=[1, 2],
                           definition_evidence=[dict(message_id=1, quote='跑图就是生成图像'),
                                                dict(message_id=2, quote='这里跑图指生成图像')])]}
    db = save(tmp_path, validate_result(value, records))
    assert db.terms('group:123')[0]['status'] == 'candidate'

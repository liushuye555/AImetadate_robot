import json
import sqlite3

from qq_onebot_whitelist.knowledge_term_inference import (
    SCHEMA, decorate_term, prepare_inference, save_annotation,
)


def _records():
    return [
        {'id': 1, 'text': '这次测试把星轨（星轨）参数调低了', 'context_only': False},
        {'id': 2, 'text': '星轨设置低一些后画面更稳定', 'context_only': False},
        {'id': 3, 'text': '旧材料提到星轨也会闪退', 'context_only': True},
    ]


def _row(**changes):
    value = {'term': '星轨', 'meaning': '参数相关说法', 'evidence_ids': [1, 2],
             'inference_kind': 'inferred', 'inference_note': '两条原消息将该词用于参数调整情境。',
             'inference_evidence': [{'id': 1, 'quote': '这次测试把星轨（星轨）参数调低了'},
                                    {'message_id': 2, 'quote': '星轨设置低一些后画面更稳定'}],
             'aliases': ['星轨'], 'alternatives': []}
    value.update(changes)
    return value


def test_default_disabled_ignores_model_inference_without_touching_definition_contexts():
    row = _row(definition_evidence=[{'message_id': 1, 'quote': '原始释义'}],
               supporting_contexts=['def2:kept'])
    result = prepare_inference(row, _records())
    assert result['inference_kind'] == 'unconfirmed'
    assert result['inference_evidence'] == []
    assert result['definition_evidence'] == row['definition_evidence']
    assert result['supporting_contexts'] == ['def2:kept']


def test_valid_alias_examples_are_merged_and_use_uniform_message_id():
    row = _row(aliases=['星轨', '星轨优化'])
    records = _records()
    records[0]['text'] += '，星轨优化需要复测'
    records[1]['text'] += '；星轨优化仍有波动'
    row['inference_evidence'] = [
        {'id': 1, 'quote': '这次测试把星轨（星轨）参数调低了'},
        {'message_id': 2, 'quote': '星轨设置低一些后画面更稳定'},
    ]
    result = prepare_inference(row, records, enabled=True)
    assert result['inference_kind'] == 'inferred'
    assert result['aliases'] == ['星轨', '星轨优化']
    assert [e['message_id'] for e in result['inference_evidence']] == [1, 2]
    assert all(set(e) == {'message_id', 'quote'} for e in result['inference_evidence'])


def test_rejects_fabricated_quote_foreign_id_duplicate_text_and_context_only_pair():
    records = _records()
    row = _row(inference_evidence=[
        {'message_id': 999, 'quote': '星轨参数很好'},
        {'message_id': 1, 'quote': '星轨意思就是星际轨道'},
        {'message_id': 1, 'quote': '这次测试把星轨（星轨）参数调低了'},
        {'message_id': 2, 'quote': '这次测试把星轨（星轨）参数调低了'},
    ])
    result = prepare_inference(row, records, enabled=True)
    assert result['inference_kind'] == 'unconfirmed'
    assert result['inference_evidence'] == []

    only_context = _row(evidence_ids=[3], inference_evidence=[
        {'message_id': 3, 'quote': '旧材料提到星轨也会闪退'},
        {'message_id': 3, 'quote': '旧材料提到星轨也会闪退'},
    ])
    assert prepare_inference(only_context, records, enabled=True)['inference_kind'] == 'unconfirmed'


def test_quote_itself_must_contain_term_or_valid_alias():
    row = _row(inference_evidence=[
        {'message_id': 1, 'quote': '参数调低了'},
        {'message_id': 2, 'quote': '设置低一些后画面更稳定'},
    ])
    result = prepare_inference(row, _records(), enabled=True)
    assert result['inference_kind'] == 'unconfirmed'
    assert result['inference_evidence'] == []


def test_ambiguous_requires_two_candidates_and_all_examples_remain_unconfirmed_as_to_truth():
    result = prepare_inference(_row(inference_kind='ambiguous', alternatives=['参数名称', '作品名称']),
                               _records(), enabled=True)
    assert result['inference_kind'] == 'ambiguous'
    assert len(result['alternatives']) == 2
    assert len(result['inference_evidence']) == 2


def test_schema_storage_and_user_term_priority():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.execute('CREATE TABLE terms(key TEXT PRIMARY KEY, origin TEXT)')
    conn.execute('INSERT INTO terms VALUES (?,?)', ('manual', 'user'))
    conn.execute('INSERT INTO terms VALUES (?,?)', ('ai', 'ai'))
    meta = prepare_inference(_row(), _records(), enabled=True)
    save_annotation(conn, 'manual', meta)
    save_annotation(conn, 'ai', meta)
    assert conn.execute('SELECT 1 FROM term_annotations WHERE term_key=?', ('manual',)).fetchone() is None
    decorated = decorate_term(conn, {'key': 'ai', 'origin': 'ai'})
    assert decorated['inference_kind'] == 'inferred'
    assert json.loads(conn.execute('SELECT evidence_json FROM term_annotations WHERE term_key="ai"').fetchone()[0])
    manual = decorate_term(conn, {'key': 'manual', 'origin': 'user'})
    assert manual['inference_kind'] == 'explicit'


def test_empty_unconfirmed_preserves_history_but_explicit_and_new_inference_update():
    conn = sqlite3.connect(':memory:')
    conn.execute(SCHEMA)
    conn.execute('CREATE TABLE terms(key TEXT PRIMARY KEY, origin TEXT)')
    conn.execute('INSERT INTO terms VALUES (?,?)', ('ai', 'ai'))
    initial = prepare_inference(_row(), _records(), enabled=True)
    save_annotation(conn, 'ai', initial)
    original = conn.execute('SELECT * FROM term_annotations WHERE term_key=?', ('ai',)).fetchone()

    save_annotation(conn, 'ai', prepare_inference(_row(), _records(), enabled=False))
    preserved = conn.execute('SELECT * FROM term_annotations WHERE term_key=?', ('ai',)).fetchone()
    assert preserved == original

    explicit = {'inference_kind': 'explicit', 'inference_note': '群内明确说明',
                'inference_evidence': [{'message_id': 1, 'quote': '星轨参数'}]}
    save_annotation(conn, 'ai', explicit)
    assert conn.execute('SELECT kind FROM term_annotations WHERE term_key=?', ('ai',)).fetchone()[0] == 'explicit'

    replacement = prepare_inference(_row(inference_note='另一组上下文用例。'), _records(), enabled=True)
    save_annotation(conn, 'ai', replacement)
    assert conn.execute('SELECT note FROM term_annotations WHERE term_key=?', ('ai',)).fetchone()[0] == '另一组上下文用例。'

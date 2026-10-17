import json
import sqlite3

import pytest

from qq_onebot_whitelist.knowledge_store import KnowledgeDB
from qq_onebot_whitelist.knowledge_subjects import canonical_subject, prepare_subjects, subjects_for
from qq_onebot_whitelist.knowledge_usage import (prepare_usage, read_catalog, set_subject_tag,
                                               usage_for, usage_markup)
from qq_onebot_whitelist.knowledge_view import render_views
from qq_onebot_whitelist.knowledge_organization import prepare_organization


def catalog(scope='group:1'):
    return [{'scope': scope, 'subject': '无限X代', 'tag': 'armor_tool',
             'aliases': ['无限二代', '无限2代', '无限四代'], 'origin': 'user', 'evidence': [], 'note': '用户确认本群用途'}]


def item(name='无限二代', scope='group:1'):
    return {'key': 'one', 'scope': scope, 'title': '安装后的使用反馈', 'body': '安装完成但未解决',
            'evidence_ids': [1], 'evidence_state': 'unresolved', 'category': 'question',
            'organization': {'subjects': [{'name': name, 'evidence': [{'message_id': 1, 'quote': name}]}]}}


def seed(tmp_path):
    conn = sqlite3.connect(tmp_path / 'bot.db')
    conn.execute('CREATE TABLE messages(id INTEGER,scope TEXT,user_id TEXT,text TEXT,raw_json TEXT,seen_at TEXT,links_json TEXT,message_key TEXT)')
    conn.execute("INSERT INTO messages VALUES (1,'group:1','anon','无限二代不做破甲题','{}','now','[]','m1')")
    conn.execute("INSERT INTO messages VALUES (2,'group:2','anon','富江破甲','{}','now','[]','m2')")
    conn.commit()
    conn.close()
    db = KnowledgeDB(tmp_path / 'knowledge.db')
    with db.conn() as conn:
        conn.execute("INSERT INTO items(key,scope,created_at,title,body,evidence_json,files_json) VALUES ('one','group:1','now','安装后的使用反馈','未解决','[1]','[]')")
    return db


def test_catalog_aliases_are_group_scoped_and_do_not_guess_tool_identity():
    row = item()
    assert subjects_for(row, catalog()) == ['无限X代']
    assert usage_for(row, catalog())[0]['tag'] == 'armor_tool'
    assert usage_for(item(scope='group:2'), catalog()) == []
    assert usage_for(item(name='无限五代'), catalog()) == []
    assert usage_for({'title': '无限二代', 'scope': 'group:1'}, catalog()) == []


def test_similar_spellings_are_separate_objects():
    assert canonical_subject('dsh-infinite-gen-5') == 'Infinite Gen'
    assert canonical_subject('IG5') == 'IG5'
    assert canonical_subject('dsh') == 'DSh'
    assert canonical_subject('无限二代') == '无限二代'
    assert canonical_subject('富江') == '富江'
    assert canonical_subject('Tomie') == 'Tomie'


@pytest.mark.parametrize('quote,name', [('dsh', 'DSh'), ('IG5', 'IG5'), ('dsh-infinite-gen-5', 'Infinite Gen')])
def test_old_unsupported_combined_label_is_split_by_its_actual_quote(quote, name):
    row = item(name='DSh / Infinite Gen')
    row['organization']['subjects'][0]['evidence'][0]['quote'] = quote
    assert subjects_for(row) == [name]


def test_old_combined_label_without_identifying_source_does_not_get_guessed():
    row = item(name='DSh / Infinite Gen')
    row['organization']['subjects'][0]['evidence'][0]['quote'] = '就是这个'
    assert subjects_for(row) == []


def test_old_combined_quote_retains_distinct_cooccurring_objects():
    row = item(name='DSh / Infinite Gen')
    row['organization']['subjects'][0]['evidence'][0]['quote'] = 'dsh-infinite-gen-5 / IG5 / DSh客户端'
    assert subjects_for(row) == ['Infinite Gen', 'IG5', 'DSh']


def test_new_tool_alias_requires_current_item_exact_source():
    label = {'name': '无限X代', 'evidence': [{'message_id': 1, 'quote': '无限二代'}]}
    assert prepare_subjects([label], {'evidence_ids': [1]}, [{'id': 1, 'text': '无限二代不做题'}], catalog())[0]['name'] == '无限X代'
    assert prepare_subjects([label], {'evidence_ids': [2]}, [{'id': 1, 'text': '无限二代不做题'}], catalog()) == []


def test_ai_usage_tag_needs_exact_object_and_purpose_not_outcome():
    raw = [{'subject': '富江', 'tag': 'armor_tool', 'evidence': [{'message_id': 1, 'quote': '用富江进行破甲失败了'}]}]
    row = {'evidence_ids': [1], 'evidence_state': 'unresolved', 'organization': {'usage_tags': raw}}
    result = prepare_organization(row, [{'id': 1, 'text': '用富江进行破甲失败了'}])
    assert result['usage_tags'][0]['tag'] == 'armor_tool'
    assert row['evidence_state'] == 'unresolved'
    assert result['progress_kind'] == 'unknown'


@pytest.mark.parametrize('quote,source', [('富江', '富江破甲失败了'), ('富江破甲成功了', '富江破甲失败了'),
                                         ('破甲工具', '破甲工具'), ('富江不是破甲工具', '富江不是破甲工具'),
                                         ('富江不做破甲题', '富江不做破甲题'),
                                         ('富江不能用来破甲', '富江不能用来破甲'),
                                         ('富江是破甲工具', '富江是破甲工具吗？'),
                                         ('富江是破甲工具', '可能富江是破甲工具'),
                                         ('用富江进行破甲', '没有用富江进行破甲'),
                                         ('富江是破甲工具', '假设富江是破甲工具'),
                                         ('用富江进行破甲', '用富江进行破甲只是猜测'),
                                         ('富江只是聊天机器人；另一个工具用来破甲', '富江只是聊天机器人；另一个工具用来破甲')])
def test_ai_cannot_assign_type_from_mention_hallucination_or_denial(quote, source):
    raw = [{'subject': '富江', 'tag': 'armor_tool', 'evidence': [{'message_id': 1, 'quote': quote}]}]
    assert prepare_usage(raw, {'evidence_ids': [1]}, [{'id': 1, 'text': source}]) == []


def test_explicit_source_definition_can_label_the_object():
    raw = [{'subject': '富江', 'tag': 'armor_tool', 'evidence': [{'message_id': 1, 'quote': '富江是破甲工具'}]}]
    assert prepare_usage(raw, {'evidence_ids': [1]}, [{'id': 1, 'text': '富江是破甲工具'}])[0]['origin'] == 'source'


def test_manual_catalog_persists_sources_adds_navigation_and_preserves_facts(tmp_path):
    db = seed(tmp_path)
    result = set_subject_tag(tmp_path, '1', '无限X代', 'armor_tool', aliases=['无限二代'],
                             note='用户确认，效果未核实', evidence=[{'message_id': 1, 'quote': '无限二代不做破甲题'}])
    assert result['updated_items'] == 1
    with db.conn() as conn:
        values = read_catalog(conn, 'group:1')
        org = json.loads(conn.execute('SELECT organization_json FROM item_organization WHERE item_key=?', ('one',)).fetchone()[0])
        stored = conn.execute('SELECT body,evidence_json,evidence_state FROM items').fetchone()
    assert values[0]['origin'] == 'user'
    assert org['subjects'][0]['name'] == '无限X代'
    assert tuple(stored) == ('未解决', '[1]', 'reported')
    assert usage_for({'scope': 'group:1', 'organization': org}, values)
    assert read_catalog(sqlite3.connect(':memory:')) == []


def test_catalog_rejects_foreign_group_evidence_and_conflicting_aliases(tmp_path):
    seed(tmp_path)
    with pytest.raises(ValueError, match='不属于本群'):
        set_subject_tag(tmp_path, '1', '富江', 'armor_tool', evidence=[{'message_id': 2, 'quote': '富江破甲'}])
    with pytest.raises(ValueError, match='规范对象冲突'):
        set_subject_tag(tmp_path, '1', '无限X代', 'armor_tool', aliases=['IG5'])
    set_subject_tag(tmp_path, '1', '无限X代', 'armor_tool', aliases=['无限二代'])
    with pytest.raises(ValueError, match='本群其他对象'):
        set_subject_tag(tmp_path, '1', '另一工具', 'armor_tool', aliases=['无限二代'])


def test_removing_alias_removes_old_navigation_but_keeps_original_fact(tmp_path):
    db = seed(tmp_path)
    set_subject_tag(tmp_path, '1', '无限X代', 'armor_tool', aliases=['无限二代'])
    result = set_subject_tag(tmp_path, '1', '无限X代', 'armor_tool', aliases=['无限四代'])
    assert result['updated_items'] == 1
    stored = db.items('group:1')[0]
    assert stored['organization']['subjects'] == []
    assert stored['body'] == '未解决'
    with db.conn() as conn:
        assert usage_for(stored, read_catalog(conn)) == []


def test_concurrent_alias_claim_has_only_one_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    db = seed(tmp_path)
    barrier = Barrier(2)
    def claim(name):
        barrier.wait(timeout=5)
        try:
            set_subject_tag(tmp_path, '1', name, 'armor_tool', aliases=['shared-alias'])
            return 'completed'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ['ToolA', 'ToolB']))
    assert sorted(results) == ['completed', 'conflict']
    with db.conn() as conn:
        assert len(read_catalog(conn, 'group:1')) == 1


def test_report_can_filter_usage_across_subjects_without_changing_status(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_view.render_evidence', lambda *_: '')
    page = render_views(tmp_path, items=[item(), item(name='智谱', scope='group:2')], runs=[], assets=[], glossary=[], subject_catalog=catalog())['knowledge.html']
    assert page.count('<article ') == 2
    assert page.count('data-usage-tags="armor_tool"') == 1
    assert 'id="usage-tag"' in page and '用途标签依据' in page
    assert '无限X代 · 破甲工具' in page and '人工确认' in page
    assert '未解决' in page


def test_catalog_types_are_attached_to_the_right_subject_in_cross_product_discussion():
    row = item()
    row['organization']['subjects'].append({'name': 'GLM', 'evidence': [{'message_id': 1, 'quote': 'GLM'}]})
    usages = usage_for(row, catalog())
    assert [entry['subject'] for entry in usages] == ['无限X代']
    assert '智谱 · 破甲工具' not in usage_markup(usages)


def test_usage_html_escapes_manual_notes_and_quotes():
    value = {**catalog()[0], 'note': '<script>alert(1)</script>', 'evidence': [{'message_id': 1, 'quote': '<img src=x>'}]}
    markup = usage_markup([value])
    assert '<script>' not in markup and '<img' not in markup and '&lt;script&gt;' in markup


def test_future_ai_receives_group_catalog_even_when_glossary_is_off(tmp_path):
    from test_knowledge import configured, record, response, MODEL
    from qq_onebot_whitelist.knowledge import analyze
    path, store = configured(tmp_path, features=('extraction',))
    record(store, '无限二代不做破甲题')
    set_subject_tag(store.path.parent, '123', '无限X代', 'armor_tool', aliases=['无限二代'])
    def request(messages, model):
        task = json.loads(messages[1]['content'])
        assert task['subject_catalog'][0]['subject'] == '无限X代'
        assert task['glossary'] == []
        result = response([1])
        result['items'][0]['organization'] = {'subjects': [{'name': '无限X代',
            'evidence': [{'message_id': 1, 'quote': '无限二代'}]}]}
        return result, 30
    result = analyze(path, '123', feature='extraction', kind='batch', model=MODEL, request=request)
    assert result['status'] == 'completed'
    stored = KnowledgeDB(store.path.parent / 'knowledge.db').items('group:123')[0]
    assert stored['organization']['subjects'][0]['name'] == '无限X代'


def test_source_role_is_kept_on_revalidation_without_changing_knowledge_state():
    from qq_onebot_whitelist.knowledge import validate_result
    row = {'title': '使用反馈', 'summary': '用富江进行破甲失败了', 'value': 'candidate', 'evidence_ids': [1], 'evidence_state': 'unresolved',
           'organization': {'subjects': [{'name': '富江', 'evidence': [{'message_id': 1, 'quote': '富江'}]}],
                            'usage_tags': [{'subject': '富江', 'tag': 'armor_tool',
                                            'evidence': [{'message_id': 1, 'quote': '用富江进行破甲失败了'}]}]}}
    records = [{'id': 1, 'text': '用富江进行破甲失败了', 'files': [], 'links': []}]
    first = validate_result({'items': [row]}, records)['items'][0]
    second = validate_result({'items': [first]}, records)['items'][0]
    assert second['organization']['usage_tags'] == first['organization']['usage_tags']
    assert second['evidence_state'] == 'unresolved'

from qq_onebot_whitelist.knowledge_subjects import canonical_subject, prepare_subjects, subjects_for
from qq_onebot_whitelist.knowledge_organization import prepare_organization
from qq_onebot_whitelist.knowledge_view import render_views


def test_canonical_subjects_group_spelling_and_versions_without_word_substrings():
    for name in ('智谱', 'GLM', 'glm5.3', 'GLM-4.7', 'Z.ai'):
        assert canonical_subject(name) == '智谱'
    assert canonical_subject('WorkBuddy') == canonical_subject('wb') == 'WorkBuddy'
    assert canonical_subject('words') == 'words'


def test_labels_require_same_item_exact_quote_and_product_mention():
    rows = [{'id': 1, 'text': 'glm5.3额度用完了'}, {'id': 2, 'text': '我的已经封了'}]
    valid = {'name': '智谱', 'evidence': [{'message_id': 1, 'quote': 'glm5.3额度用完了'}]}
    assert prepare_subjects([valid], {'evidence_ids': [1]}, rows)[0]['name'] == '智谱'
    assert prepare_subjects([valid], {'evidence_ids': [2]}, rows) == []
    assert prepare_subjects([{'name': 'ChatGPT', 'evidence': [{'message_id': 2, 'quote': '我的已经封了'}]}],
                            {'evidence_ids': [2]}, rows) == []
    valid['evidence'][0]['quote'] = 'glm已经恢复'
    assert prepare_subjects([valid], {'evidence_ids': [1]}, rows) == []


def test_organization_keeps_subject_navigation_independent_from_referent_and_status():
    record = {'id': 1, 'text': 'GLM的额度什么时候恢复？'}
    row = {'evidence_ids': [1], 'organization': {'subjects': [{'name': '智谱',
        'evidence': [{'message_id': 1, 'quote': record['text']}]}]}}
    org = prepare_organization(row, [record])
    assert org['subjects'][0]['name'] == '智谱'
    assert org['subject']['ambiguous'] is True
    assert org['progress_kind'] == 'unknown'


def test_report_groups_cases_without_combining_content_or_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_view.render_evidence', lambda _, scope, ids: str(ids))
    items = [{'key': str(i), 'scope': 'group:1', 'title': title, 'body': '各自的原始情形',
        'evidence_ids': [i], 'organization': {'subjects': [{'name': name,
        'evidence': [{'message_id': i, 'quote': name}]}]}} for i, title, name in (
        (1, 'GLM额度刷新', 'GLM'), (2, '智谱接口报错', '智谱'), (3, 'WorkBuddy登录', 'WorkBuddy'))]
    page = render_views(tmp_path, items=items, runs=[], glossary=[], assets=[])['knowledge.html']
    assert page.count('<article ') == 3
    assert page.count('data-subject-group=') == 2
    assert '按主题浏览' in page and 'data-subject-name="智谱"' in page
    assert 'GLM额度刷新' in page and '智谱接口报错' in page
    assert '情形类型' in page


def test_explicit_unknown_subject_does_not_get_guessed_from_title():
    assert subjects_for({'title': 'GPT封号', 'organization': {'subjects': []}}) == []


def test_explicit_quote_can_identify_theme_without_identifying_current_pronoun():
    row = {'name': '智谱', 'evidence': [{'message_id': 1, 'quote': 'GLM额度'}]}
    records = [{'id': 2, 'text': '我也是', 'quoted_id': 1, 'quoted_text': 'GLM额度用完了'}]
    assert prepare_subjects([row], {'evidence_ids': [1, 2]}, records)[0]['name'] == '智谱'


def test_subject_labels_are_escaped_in_navigation_and_attributes(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_view.render_evidence', lambda *_: '')
    label = '<img src=x onerror=alert(1)>'
    page = render_views(tmp_path, items=[{'title': '测试', 'organization': {'subjects': [
        {'name': label, 'evidence': [{'message_id': 1, 'quote': label}]}]}}],
        runs=[], glossary=[], assets=[])['knowledge.html']
    assert '<img src=x' not in page and '&lt;img' in page


def test_cross_subject_case_has_one_body_and_both_navigation_entries(tmp_path, monkeypatch):
    monkeypatch.setattr('qq_onebot_whitelist.knowledge_view.render_evidence', lambda *_: '')
    labels = [{'name': name, 'evidence': [{'message_id': 1, 'quote': name}]}
              for name in ('WorkBuddy', 'GLM')]
    page = render_views(tmp_path, items=[{'title': '接入对比', 'body': '独立的原始对比记录',
        'organization': {'subjects': labels}}], runs=[], glossary=[], assets=[])['knowledge.html']
    assert page.count('<article ') == 1 and page.count('data-subject-group=') == 1
    assert 'data-subject-name="WorkBuddy / 智谱"' in page
    assert 'data-subject-name="WorkBuddy"' in page and 'data-subject-name="智谱"' in page
    assert page.count('独立的原始对比记录') == 2  # Excerpt and original detail, one card.


def test_already_available_attachment_preview_can_support_subject_label():
    record = {'id': 1, 'text': '见附件', 'files': [{'preview': {'text': 'Python调试教程'}}]}
    assert prepare_subjects([{'name': 'Python', 'evidence': [{'message_id': 1, 'quote': 'Python'}]}],
                            {'evidence_ids': [1]}, [record])[0]['name'] == 'Python'


def test_legacy_confirmed_subject_survives_missing_new_model_field():
    row = {'evidence_ids': [1], 'organization': {'subject': {'name': 'GLM',
        'evidence': [{'message_id': 1, 'quote': 'GLM额度'}]}}}
    organization = prepare_organization(row, [{'id': 1, 'text': 'GLM额度'}])
    assert organization['subjects_complete'] is False
    assert subjects_for({'organization': organization}) == ['智谱']

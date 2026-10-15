import pytest

from qq_onebot_whitelist.knowledge import validate_result
from qq_onebot_whitelist.knowledge_layers import prepare_details


def test_resource_links_require_cited_original_url():
    rows = [dict(id=1, text='分享项目', time='2026-10-15T12:00:00+08:00', links=['https://example.test/project'])]
    row = dict(category='resource', evidence_ids=[1], resource={'name': '工具', 'url': 'https://evil.invalid', 'purpose': '测试'})
    assert 'url' not in prepare_details(row, rows)['resource']
    row['resource']['url'] = 'https://example.test/project'
    details = prepare_details(row, rows)
    assert details['resource']['url'] == row['resource']['url']
    assert details['resource']['status'] == 'unverified'
    assert details['source_time'] == '2026-10-15T04:00:00+00:00'


def test_invalid_layer_is_rejected_and_legacy_questions_are_classified():
    with pytest.raises(ValueError):
        prepare_details(dict(category=['bad'], evidence_ids=[1]), [])
    details = prepare_details(dict(kind='未解决', evidence_ids=[1]), [])
    assert details['category'] == 'question' and details['source_time'] is None

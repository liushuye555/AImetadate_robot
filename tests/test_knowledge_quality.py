import sqlite3

from qq_onebot_whitelist.knowledge_quality import QUALITY_SYSTEM, normalize_quality


def _item(**updates):
    item = {
        'title': '节点排错', 'summary': '按顺序更改设置后恢复运行', 'kind': '排错',
        'topic': '绘图节点', 'value': 'high', 'evidence_state': 'reported',
        'category': 'knowledge', 'evidence_ids': [1, 2], 'file_ids': [],
        'quality': {
            'basis': 'firsthand_result', 'conditions': ['Windows 11，节点版本 2.1'],
            'actions': ['将缓存目录改到本地磁盘'],
            'result_quote': {'message_id': 2, 'quote': '改到本地盘后重启，节点能正常运行了'},
        },
    }
    item.update(updates)
    return item


def _records():
    return [
        {'id': 1, 'text': '节点一直报错，有人遇到吗？'},
        {'id': 2, 'text': 'Windows 11，节点版本 2.1。将缓存目录改到本地磁盘。改到本地盘后重启，节点能正常运行了'},
        {'id': 3, 'text': '转发：某插件今日维护，暂时无法下载'},
    ]


def test_reported_claim_marked_high_is_downgraded():
    item = _item(quality={**_item()['quality'], 'basis': 'reproducible_method',
                          'conditions': ['全部机器通用'], 'actions': ['开启自动优化']})
    result = normalize_quality(item, _records())
    assert result['value'] == 'candidate'
    assert result['quality']['basis'] == 'reproducible_method'


def test_announcement_is_transient_candidate():
    item = _item(kind='公告', evidence_ids=[3], evidence_state='reported',
                 category='knowledge', quality={'basis': 'announcement', 'conditions': [],
                 'actions': [], 'result_quote': None})
    result = normalize_quality(item, _records())
    assert result['value'] == 'candidate'
    assert result['category'] == 'transient'


def test_quote_must_be_exact_and_in_item_evidence():
    item = _item(quality={**_item()['quality'], 'result_quote': {
        'message_id': 1, 'quote': '改到本地盘后重启，节点能正常运行了'}})
    assert normalize_quality(item, _records())['value'] == 'candidate'
    item['quality']['result_quote'] = {'message_id': 2, 'quote': '重启后正常'}
    assert normalize_quality(item, _records())['value'] == 'candidate'


def test_verified_specific_feedback_can_remain_high():
    item = _item(evidence_state='verified')
    result = normalize_quality(item, _records())
    assert result['value'] == 'high'


def test_specific_unverified_tutorial_can_be_high_without_changing_reported_state():
    item = _item(quality={**_item()['quality'], 'basis': 'reproducible_method'},
                 evidence_state='reported')
    result = normalize_quality(item, _records())
    assert result['value'] == 'high'
    assert result['evidence_state'] == 'reported'


def test_quality_cannot_promote_candidate_or_unresolved_disputed_content():
    for changes in ({'value': 'candidate'}, {'evidence_state': 'unresolved'}, {'evidence_state': 'disputed'}):
        assert normalize_quality(_item(**changes), _records())['value'] == 'candidate'


def test_personal_claim_title_is_qualified_once_and_stays_candidate():
    item = _item(quality={**_item()['quality'], 'basis': 'personal_opinion'})
    first = normalize_quality(item, _records())
    assert first['title'].startswith('群友说法：') and first['value'] == 'candidate'
    assert normalize_quality(first, _records())['title'] == first['title']


def test_legacy_readonly_database_can_be_rendered_without_quality_table(tmp_path):
    from qq_onebot_whitelist.knowledge_quality import decorate_quality
    path = tmp_path / 'old.db'
    sqlite3.connect(path).close()
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        assert decorate_quality(conn, {'key': 'old-item', 'title': 'Old title'})['title'] == 'Old title'
    finally:
        conn.close()


def test_file_preview_can_support_method_quote_and_details():
    item = _item(evidence_ids=[4], quality={
        'basis': 'reproducible_method', 'conditions': ['Python 3.12'],
        'actions': ['运行 python -m app'],
        'result_quote': {'message_id': 4, 'quote': '运行 python -m app'},
    })
    records = [{'id': 4, 'text': '这是一个项目文件', 'files': [
        {'preview': {'text': '环境：Python 3.12。运行 python -m app。'}}]}]
    assert normalize_quality(item, records)['value'] == 'high'


def test_missing_quality_is_safe_candidate():
    item = _item()
    item.pop('quality')
    result = normalize_quality(item, _records())
    assert result['value'] == 'candidate'
    assert result['quality'] is None


def test_promotion_is_dropped_and_prompt_requires_quality_schema():
    item = _item(quality={'basis': 'promotion', 'conditions': [], 'actions': [], 'result_quote': None})
    assert normalize_quality(item, _records()) is None
    assert 'result_quote' in QUALITY_SYSTEM and 'promotion' in QUALITY_SYSTEM


def test_quality_annotation_round_trips_separately():
    from qq_onebot_whitelist.knowledge_quality import (
        decorate_quality, ensure_schema, save_quality,
    )

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    item = normalize_quality(_item(), _records())
    save_quality(conn, 'item-1', item)
    restored = decorate_quality(conn, {'key': 'item-1', 'value': item['value']})
    assert restored['quality'] == item['quality']
    assert restored['quality_reason'] == item['quality_reason']

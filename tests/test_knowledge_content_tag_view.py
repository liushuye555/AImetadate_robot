from qq_onebot_whitelist import knowledge_view
from qq_onebot_whitelist.knowledge_view import render_views


def _render(tmp_path, items, threads=()):
    return render_views(tmp_path, items=list(items), runs=[], glossary=[], assets=[], threads=list(threads))['knowledge.html']


def test_topic_only_card_is_searchable_in_directory_and_keeps_subject_unknown_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, 'render_evidence', lambda *_: '')
    row = {'key': 'topic-only', 'scope': 'group:1', 'title': '虚拟卡开通', 'body': '用户询问虚拟卡是否可用',
           'organization': {'subjects': [], 'topic_tags': [{'name': '虚拟卡', 'origin': 'ai',
               'evidence': [{'message_id': 12, 'quote': '正在问虚拟卡如何申请'}]}]}}
    page = _render(tmp_path, [row])
    assert 'data-subject-name="虚拟卡"' in page
    assert 'data-subjects="' in page
    assert '虚拟卡' in page and 'AI归类' in page
    assert '其他与对象待确认' not in page
    assert '对象指代待确认' not in page
    assert '主题归类依据' in page and '原消息 #12' in page and '正在问虚拟卡如何申请' in page
    assert '不表示当前使用成功' in page
    assert '按平台、工具或资料主题浏览' in page
    assert '分类参考：互联网常识与谐音' in page
    assert '不能替代原消息证据' in page


def test_entities_precede_content_tags_and_all_labels_are_escaped(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, 'render_evidence', lambda *_: '')
    entity = {'name': 'WorkBuddy', 'evidence': [{'message_id': 8, 'quote': 'WorkBuddy登录'}]}
    dangerous = '<img src=x onerror=alert(1)>'
    tag = {'name': dangerous, 'origin': 'ai', 'evidence': [{'message_id': 8, 'quote': '<script>alert(1)</script>'}]}
    monkeypatch.setattr(knowledge_view, 'topic_tags_for', lambda _row: [dangerous])
    row = {'key': 'with-entity', 'scope': 'group:1', 'title': '测试', 'body': '原文',
           'organization': {'subjects': [entity], 'topic_tags': [tag]}}
    page = _render(tmp_path, [row])
    assert 'data-subject-name="WorkBuddy / &lt;img' in page
    assert '<img src=x' not in page and '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page


def test_thread_aggregates_topic_labels_across_events_without_copying_the_card(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_view, 'render_evidence', lambda *_: '')
    thread = {'scope': 'group:1', 'title': '闲鱼虚拟卡讨论', 'key': 'thread-1', 'status': 'open',
              'events': [
                  {'item_key': 'a', 'status': 'open', 'summary': '第一次提到闲鱼', 'evidence_ids': [],
                   'organization': {'topic_tags': [{'name': '闲鱼', 'origin': 'ai', 'evidence': [
                       {'message_id': 1, 'quote': '闲鱼平台'}]}]}},
                  {'item_key': 'b', 'status': 'open', 'summary': '第二次提到虚拟卡', 'evidence_ids': [],
                   'organization': {'topic_tags': [{'name': '虚拟卡', 'origin': 'ai', 'evidence': [
                       {'message_id': 2, 'quote': '虚拟卡申请'}]}]}}
              ]}
    page = _render(tmp_path, [], [thread])
    assert '闲鱼' in page and '虚拟卡' in page and 'AI归类' in page
    assert page.count('<article ') == 1
    assert page.count('第一次提到闲鱼') == 1
    # The current latest-event excerpt also appears in the existing timeline.
    assert page.count('第二次提到虚拟卡') == 2

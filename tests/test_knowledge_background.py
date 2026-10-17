from qq_onebot_whitelist import knowledge_background as background
from qq_onebot_whitelist.knowledge_subjects import prepare_subjects
from qq_onebot_whitelist.knowledge_tags import prepare_topic_tags


def test_homophone_platform_mapping_requires_trade_context():
    label = {'name': '闲鱼', 'evidence': [{'message_id': 1, 'quote': '咸鱼'}]}
    item = {'evidence_ids': [1]}
    assert prepare_subjects([label], item, [{'id': 1, 'text': '咸鱼三块多一个，国内号'}])[0]['name'] == '闲鱼'
    assert prepare_subjects([label], item, [{'id': 1, 'text': '买了咸鱼，回去做饭'}]) == []
    assert prepare_subjects([label], item, [{'id': 1, 'text': '咸鱼很好吃'}]) == []
    label['name'] = '咸鱼'
    assert prepare_subjects([label], item, [{'id': 1, 'text': '咸鱼三块多一个，国内号'}])[0]['name'] == '闲鱼'
    assert prepare_subjects([label], item, [{'id': 1, 'text': '买了咸鱼，回去做饭'}])[0]['name'] == '咸鱼'


def test_confirmed_group_alias_has_precedence_over_background():
    catalog = [{'subject': '群内项目', 'aliases': ['咸鱼']}]
    label = {'name': '咸鱼', 'evidence': [{'message_id': 1, 'quote': '咸鱼'}]}
    assert prepare_subjects([label], {'evidence_ids': [1]}, [{'id': 1, 'text': '咸鱼国内号项目'}], catalog)[0]['name'] == '群内项目'
    label['name'] = '闲鱼'
    assert prepare_subjects([label], {'evidence_ids': [1]}, [{'id': 1, 'text': '咸鱼账号买卖'}], catalog) == []


def test_background_cannot_supply_a_missing_current_source():
    label = {'name': '闲鱼', 'evidence': [{'message_id': 9, 'quote': '咸鱼'}]}
    assert prepare_subjects([label], {'evidence_ids': [1]}, [{'id': 1, 'text': '国内号项目'}]) == []
    assert prepare_topic_tags([{'name': '虚拟卡', 'evidence': [{'message_id': 1, 'quote': '虚拟visa卡'}]}],
                              {'evidence_ids': [1]}, [{'id': 1, 'text': '这个中国不行'}]) == []


def test_source_named_platform_is_recovered_even_if_ai_omits_entity_field():
    from qq_onebot_whitelist.knowledge_organization import prepare_organization
    result = prepare_organization({'evidence_ids': [1], 'organization': {'subjects': [], 'topic_tags': []}},
                                  [{'id': 1, 'text': '咸鱼三块多一个，国内号'}])
    assert result['subjects'][0]['name'] == '闲鱼'
    assert result['subject']['ambiguous'] is True


def test_ambiguous_slang_is_a_hint_not_an_automatic_entity_alias():
    for term in ('梯子', '料', '车', '五代', '号'):
        assert background.canonical_in_context(term, [term]) == term
    context = background.context_for([{'text': '谁有梯子？'}])
    assert any(entry['canonical'] == '网络代理' for entry in context['entries'])
    assert '当前事实' not in str(context['entries'])


def test_dictionary_is_versioned_and_exposes_sources_without_network():
    data = background.load_background()
    assert data['version'] >= 1 and data['updated_at'] == '2026-10-17'
    assert len(data['entries']) >= 10
    assert all(entry.get('limits') for entry in data['entries'])
    assert any(entry['sources'] for entry in data['entries'])
    assert len(background.background_fingerprint()) == 64


def test_unrelated_background_entries_are_not_sent_to_the_model():
    context = background.context_for([{'text': '虚拟visa卡怎么开'}])
    assert any(entry['canonical'] == '虚拟卡' for entry in context['entries'])
    assert not any(entry['canonical'] == '闲鱼' for entry in context['entries'])

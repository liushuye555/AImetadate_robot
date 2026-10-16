from datetime import datetime, timezone

import pytest

from qq_onebot_whitelist.knowledge_lifecycle import lifecycle_for


class Profile:
    def __init__(self, enabled, settings=None):
        self.enabled = enabled
        self.settings = settings or {}

    def option_enabled(self, section, key):
        return section == 'lifecycle' and key == 'enabled' and self.enabled


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_disabled_and_default_inherited_settings_do_not_enable_lifecycle():
    row = {'category': 'transient', 'source_time': '2026-10-01T00:00:00Z'}
    result = lifecycle_for(row, profile=Profile(False, {'lifecycle': {'enabled': True}}), now=NOW)
    assert result['lane'] == 'knowledge'
    assert result['expires_at'] is None
    assert not result['archived']


def test_source_time_not_write_time_drives_expiry_and_resource_is_not_kept_open_forever():
    row = {'category': 'resource', 'status': 'open', 'source_time': '2026-09-01T00:00:00Z',
           'created_at': '2026-10-15T00:00:00Z', 'updated_at': '2026-10-15T00:00:00Z'}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['lane'] == 'archive'
    assert result['archived']
    assert result['last_progress_at'] == '2026-09-01T00:00:00Z'
    assert '时效' in result['reason']


def test_reusable_knowledge_never_auto_expires_even_when_very_old():
    row = {'category': 'knowledge', 'status': 'open',
           'source_time': '1976-10-01T00:00:00Z'}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['lane'] == 'knowledge'
    assert result['expires_at'] is None
    assert not result['archived']


def test_verified_resolved_question_becomes_preserved_knowledge():
    row = {'category': 'question', 'status': 'resolved', 'evidence_state': 'verified',
           'source_time': '2020-01-01T00:00:00Z'}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['lane'] == 'knowledge' and result['expires_at'] is None
    assert '已验证解决' in result['reason']
    row['evidence_state'] = 'reported'
    assert lifecycle_for(row, profile=Profile(True), now=NOW)['lane'] == 'archive'


def test_resource_policy_precedes_generic_detailed_retention_class():
    row = {'category': 'resource', 'source_time': '2026-09-20T00:00:00Z',
           'organization': {'retention_class': 'detailed'}}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['expires_at'] == '2026-10-20T00:00:00Z'
    assert not result['archived']


def test_unresolved_evidence_only_routes_unclassified_rows_to_followup():
    profile = Profile(True)
    unresolved = {'events': [{'source_time': '2026-10-10T00:00:00Z',
                              'evidence_state': 'unresolved'}]}
    knowledge = {'category': 'knowledge', 'events': unresolved['events']}
    assert lifecycle_for(unresolved, profile=profile, now=NOW)['lane'] == 'followup'
    assert lifecycle_for(knowledge, profile=profile, now=NOW)['lane'] == 'knowledge'


def test_repeat_does_not_extend_but_new_information_does():
    row = {'category': 'question', 'events': [
        {'source_time': '2026-10-01T00:00:00Z'},
        {'source_time': '2026-10-14T00:00:00Z', 'organization': {'progress_kind': 'repeat'}},
    ]}
    profile = Profile(True, {'lifecycle': {'brief_days': 3}})
    expired = lifecycle_for(row, profile=profile, now=NOW)
    assert expired['archived']
    assert expired['last_progress_at'] == '2026-10-01T00:00:00Z'
    row['events'][1]['organization']['progress_kind'] = 'new_information'
    current = lifecycle_for(row, profile=profile, now=NOW)
    assert current['lane'] == 'followup'
    assert not current['archived']
    assert current['last_progress_at'] == '2026-10-14T00:00:00Z'


def test_repeat_cannot_switch_to_longer_retention_and_revive_expired_question():
    row = {'category': 'question', 'events': [
        {'source_time': '2026-10-01T00:00:00Z', 'category': 'question',
         'organization': {'retention_class': 'brief'}},
        {'source_time': '2026-10-05T00:00:00Z', 'category': 'question',
         'organization': {'retention_class': 'detailed', 'progress_kind': 'repeat'}}]}
    result = lifecycle_for(row, profile=Profile(True), now='2026-10-08T00:00:00Z')
    assert result['archived'] and result['expires_at'] == '2026-10-04T00:00:00Z'
    row['events'][1]['category'] = 'knowledge'
    assert lifecycle_for(row, profile=Profile(True), now='2026-10-08T00:00:00Z')['archived']


def test_exact_progress_time_wins_over_later_repeated_evidence_time():
    row = {'category': 'question', 'events': [
        {'source_time': '2026-09-28T00:00:00Z'},
        {'source_time': '2026-10-15T00:00:00Z', 'organization': {
            'progress_kind': 'new_information', 'progress_time': '2026-10-01T00:00:00Z',
            'first_source_time': '2026-10-01T00:00:00Z'}}]}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['last_progress_at'] == '2026-10-01T00:00:00Z'
    assert result['archived']
    standalone = {'category': 'question', 'source_time': '2026-10-15T00:00:00Z',
                  'organization': {'first_source_time': '2026-10-01T00:00:00Z'}}
    assert lifecycle_for(standalone, profile=Profile(True), now=NOW)['archived']


@pytest.mark.parametrize('thread', [True, False])
def test_first_event_or_standalone_can_include_later_real_progress(thread):
    event = {'category': 'question', 'source_time': '2026-10-15T00:00:00Z',
             'organization': {'first_source_time': '2026-10-01T00:00:00Z',
                 'progress_kind': 'new_information', 'progress_time': '2026-10-15T00:00:00Z'}}
    row = {'events': [event]} if thread else event
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert not result['archived'] and result['last_progress_at'] == '2026-10-15T00:00:00Z'


def test_missing_dates_do_not_expire_or_use_write_timestamps():
    row = {'category': 'transient', 'created_at': '2020-01-01T00:00:00Z',
           'events': [{'source_time': None, 'created_at': '2020-01-01T00:00:00Z'}]}
    result = lifecycle_for(row, profile=Profile(True), now=NOW)
    assert result['expires_at'] is None
    assert result['last_progress_at'] is None
    assert not result['archived']


def test_manual_override_archived_and_active():
    row = {'category': 'resource', 'source_time': '2020-01-01T00:00:00Z'}
    profile = Profile(True)
    archived = lifecycle_for(row, profile=profile, now=NOW, manual='archived')
    active = lifecycle_for(row, profile=profile, now=NOW, manual={'state': 'active'})
    assert archived['lane'] == 'archive' and archived['archived']
    assert active['lane'] == 'knowledge' and not active['archived']
    assert active['expires_at'] is None


@pytest.mark.parametrize('value', [True, False, 0, 3651, '3'])
def test_retention_days_are_strict_bounded_integers(value):
    row = {'category': 'transient', 'source_time': '2026-10-01T00:00:00Z'}
    with pytest.raises(ValueError):
        lifecycle_for(row, profile=Profile(True, {'lifecycle': {'transient_days': value}}), now=NOW)


def test_naive_now_is_rejected_when_expiry_is_calculated():
    row = {'category': 'transient', 'source_time': '2026-10-01T00:00:00Z'}
    with pytest.raises(ValueError):
        lifecycle_for(row, profile=Profile(True), now=datetime(2026, 10, 16))

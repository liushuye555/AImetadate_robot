"""Pure lifecycle classification for knowledge rows and topic threads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


_DAY_DEFAULTS = {
    'brief_days': 3,
    'detailed_days': 14,
    'transient_days': 3,
    'resource_days': 30,
}


def _parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _option_enabled(profile):
    if profile is None:
        return False
    checker = getattr(profile, 'option_enabled', None)
    return bool(callable(checker) and checker('lifecycle', 'enabled'))


def _days(settings, key):
    value = settings.get(key, _DAY_DEFAULTS[key])
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3650:
        raise ValueError(f'{key} 必须是 1..3650 的整数')
    return value


def _organization(row):
    value = row.get('organization')
    return value if isinstance(value, dict) else {}


def _is_progress(row):
    org = _organization(row)
    return org.get('progress_kind') == 'new_information' and (
        'progress_time' not in org or _parse_time(org.get('progress_time')) is not None)


def _retention_days(row, settings):
    classified = _latest_classification(row)
    org = _organization(classified)
    retention = org.get('retention_class')
    category = str(classified.get('category') or row.get('category') or '').casefold()
    # Volatile categories use their dedicated policy regardless of any
    # generic detailed classification attached by an extractor.
    if category in {'resource', '资料', '资源'}:
        return _days(settings, 'resource_days')
    if category in {'transient', '时效', '时效性'}:
        return _days(settings, 'transient_days')
    if retention == 'brief':
        return _days(settings, 'brief_days')
    # Unknown retention classes must not force the short brief policy.
    return _days(settings, 'detailed_days')


def _latest_classification(row, *, meaningful=True):
    events = row.get('events')
    if not isinstance(events, list):
        return row
    valid = [(stamp, index, event) for index, event in enumerate(events)
             if isinstance(event, dict)
             if (stamp := _parse_time(event.get('source_time'))) is not None]
    if valid:
        valid.sort(key=lambda point: (point[0], point[1]))
        if not meaningful:
            return valid[-1][2]
        selected = valid[0][2]
        for _, _, event in valid[1:]:
            if _is_progress(event):
                selected = event
        return selected
    for event in reversed(events):
        if isinstance(event, dict):
            return event
    return row


def _progress_times(row):
    events = row.get('events')
    if not isinstance(events, list):
        events = []
    points = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        stamp = _parse_time(_organization(event).get('first_source_time')) or _parse_time(event.get('source_time'))
        if stamp is not None:
            points.append((stamp, index, event))
    # A standalone item has its own original source timestamp.
    if not events:
        stamp = _parse_time(_organization(row).get('first_source_time')) or _parse_time(row.get('source_time'))
        if stamp is not None:
            progress = _parse_time(_organization(row).get('progress_time')) if _is_progress(row) else None
            return stamp, max(stamp, progress) if progress else stamp
    if not points:
        return None, None
    points.sort(key=lambda point: (point[0], point[1]))
    first = points[0][0]
    last_progress = first
    for stamp, _, event in points:
        org = event.get('organization')
        kind = org.get('progress_kind') if isinstance(org, dict) else None
        progress_stamp = _parse_time(org.get('progress_time')) if isinstance(org, dict) and 'progress_time' in org else stamp
        if kind == 'new_information' and progress_stamp is not None and progress_stamp >= last_progress:
            last_progress = progress_stamp
    return first, last_progress


def lifecycle_for(row, *, profile=None, now=None, manual=None):
    """Classify one topic/item without mutating it or inferring resolved state.

    ``manual`` may be ``"archived"``/``"active"`` or a mapping with a
    ``state`` field. Invalid/missing source dates deliberately disable expiry.
    """
    row = row if isinstance(row, dict) else {}
    manual_state = manual.get('state') if isinstance(manual, dict) else manual
    classification = _latest_classification(row)
    latest = _latest_classification(row, meaningful=False)
    category = str(classification.get('category', row.get('category')) or '').casefold()
    evidence_state = str(latest.get('evidence_state') or '').casefold()
    resolved = (str(row.get('status') or latest.get('status') or '').casefold() == 'resolved'
                and evidence_state == 'verified')
    # An explicit knowledge/category label wins over a generic unresolved
    # evidence marker; only unclassified unresolved evidence is a question.
    question = not resolved and (category in {'question', 'unresolved', '问题', '未解决', '求助'}
                                or (not category and evidence_state == 'unresolved'))
    lane = 'followup' if question else 'knowledge'
    first, last_progress = _progress_times(row)
    expires_at = None
    archived = False
    reason = '已验证解决，作为知识记录保留' if resolved else '待跟进问题仍未解决' if question else '知识记录保留'

    if manual_state == 'archived':
        lane, archived, reason = 'archive', True, '人工归档'
    elif manual_state == 'active':
        reason = '人工保留，暂停自动过期'
    elif _option_enabled(profile) and (
            question or category in {'transient', '时效', '时效性', 'resource', '资料', '资源'}):
        settings = getattr(profile, 'settings', {}) or {}
        lifecycle = settings.get('lifecycle', {}) if isinstance(settings, dict) else {}
        if not isinstance(lifecycle, dict):
            lifecycle = {}
        days = _retention_days(row, lifecycle)
        # Calculate from the first source timestamp, then advance only on
        # explicitly classified new information. Repeats/unknowns never reset it.
        if first is not None:
            # _progress_times returns last progress; use it for the effective
            # start while retaining the first source timestamp for reporting.
            expires_at = last_progress + timedelta(days=days)
            current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
            if current is None:
                raise ValueError('now 必须是带时区的 datetime 或 ISO 时间')
            if current >= expires_at:
                lane, archived = 'archive', True
                reason = ('未解决问题超过保留期，已归档' if question
                          else '记录已超过时效保留期，已归档')
            else:
                reason = '待跟进问题仍在保留期' if question else '记录仍在保留期'

    return {
        'lane': lane,
        'reason': reason,
        'expires_at': expires_at.isoformat().replace('+00:00', 'Z') if expires_at else None,
        'last_progress_at': last_progress.isoformat().replace('+00:00', 'Z') if last_progress else None,
        'archived': archived,
        'category': category,
    }

from __future__ import annotations

from datetime import datetime, time
import re


WINDOW_RE = re.compile(r'^(\d{2}):(\d{2})-(\d{2}):(\d{2})$')

WEEKDAY_KEYS = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
_WEEKDAY_ALIASES = {'周六': 'sat', '周日': 'sun', '星期六': 'sat', '星期日': 'sun',
                    'monday': 'mon', 'tuesday': 'tue', 'wednesday': 'wed',
                    'thursday': 'thu', 'friday': 'fri', 'saturday': 'sat', 'sunday': 'sun'}


def normalize_weekdays(items) -> list[str]:
    """归一星期标识为 mon/tue/... 列表；无效项忽略。"""
    result = []
    for item in items or ():
        key = str(item).strip().lower()
        key = _WEEKDAY_ALIASES.get(key, key)
        if key in WEEKDAY_KEYS and key not in result:
            result.append(key)
    return result


def all_day_today(weekdays, now: datetime) -> bool:
    """now 的星期是否在全天允许列表里（如 DeepSeek 周末全天错峰）。"""
    enabled = normalize_weekdays(weekdays)
    if not enabled:
        return False
    keys = list(WEEKDAY_KEYS)
    return keys[now.weekday()] in enabled


def normalize_time_windows(windows: list[str]) -> list[str]:
    result = []
    for raw in windows:
        value = str(raw).strip()
        match = WINDOW_RE.fullmatch(value)
        if not match:
            raise ValueError(f'无效时间段：{value}，格式应为 HH:MM-HH:MM')
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
            raise ValueError(f'无效时间段：{value}')
        if (start_hour, start_minute) == (end_hour, end_minute):
            raise ValueError(f'无效时间段：{value}，开始和结束时间不能相同')
        result.append(value)
    return result


def _parse_time(value: str) -> time:
    hour, minute = value.strip().split(':', 1)
    return time(int(hour), int(minute))


def is_in_time_windows(now: datetime, windows: list[str]) -> bool:
    normalized = normalize_time_windows(windows)
    if not normalized:
        return True
    current = now.time().replace(second=0, microsecond=0)
    for window in normalized:
        start_text, end_text = window.split('-', 1)
        start = _parse_time(start_text)
        end = _parse_time(end_text)
        if start <= end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False

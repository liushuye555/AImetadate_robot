from __future__ import annotations

from datetime import datetime, time


def _parse_time(value: str) -> time:
    hour, minute = value.strip().split(':', 1)
    return time(int(hour), int(minute))


def is_in_time_windows(now: datetime, windows: list[str]) -> bool:
    if not windows:
        return True
    current = now.time().replace(second=0, microsecond=0)
    for window in windows:
        start_text, end_text = window.split('-', 1)
        start = _parse_time(start_text)
        end = _parse_time(end_text)
        if start <= end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False

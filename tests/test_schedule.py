from datetime import datetime

from qq_onebot_whitelist.schedule import is_in_time_windows


def test_time_windows_support_daytime_and_overnight_ranges():
    assert is_in_time_windows(datetime(2026, 7, 10, 1, 0), ['00:30-08:30']) is True
    assert is_in_time_windows(datetime(2026, 7, 10, 12, 0), ['00:30-08:30']) is False
    assert is_in_time_windows(datetime(2026, 7, 10, 23, 30), ['23:00-07:00']) is True
    assert is_in_time_windows(datetime(2026, 7, 10, 8, 0), ['23:00-07:00']) is False
    assert is_in_time_windows(datetime(2026, 7, 10, 12, 0), []) is True

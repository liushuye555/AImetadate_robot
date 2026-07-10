from datetime import datetime

import pytest

from qq_onebot_whitelist.schedule import is_in_time_windows, normalize_time_windows


def test_time_windows_support_daytime_and_overnight_ranges():
    assert is_in_time_windows(datetime(2026, 7, 10, 1, 0), ['00:30-08:30']) is True
    assert is_in_time_windows(datetime(2026, 7, 10, 12, 0), ['00:30-08:30']) is False
    assert is_in_time_windows(datetime(2026, 7, 10, 23, 30), ['23:00-07:00']) is True
    assert is_in_time_windows(datetime(2026, 7, 10, 8, 0), ['23:00-07:00']) is False
    assert is_in_time_windows(datetime(2026, 7, 10, 12, 0), []) is True


def test_normalize_time_windows_accepts_multiple_ranges():
    assert normalize_time_windows(['00:30-08:30', '12:00-13:00', '23:00-07:00']) == [
        '00:30-08:30', '12:00-13:00', '23:00-07:00',
    ]


@pytest.mark.parametrize('value', ['24:00-08:00', '8:00-09:00', '09:60-10:00', '09:00'])
def test_normalize_time_windows_rejects_invalid_ranges(value):
    with pytest.raises(ValueError):
        normalize_time_windows([value])


def test_equal_window_boundaries_are_rejected():
    with pytest.raises(ValueError):
        normalize_time_windows(['08:00-08:00'])

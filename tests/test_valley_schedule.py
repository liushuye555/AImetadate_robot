from datetime import datetime
from pathlib import Path

from qq_onebot_whitelist.schedule import all_day_today, normalize_weekdays


def test_normalize_weekdays_accepts_aliases():
    assert normalize_weekdays(['Sat', '周日', '星期六', 'bogus']) == ['sat', 'sun']


def test_all_day_today_weekend_policy():
    weekend = ['sat', 'sun']
    assert all_day_today(weekend, datetime(2026, 9, 12)) is True   # 周六
    assert all_day_today(weekend, datetime(2026, 9, 13)) is True   # 周日
    assert all_day_today(weekend, datetime(2026, 9, 9, 12, 0)) is False  # 周三白天


def test_empty_weekday_list_never_all_day():
    assert all_day_today([], datetime(2026, 9, 12)) is False


def test_config_reads_all_day_weekdays(tmp_path):
    import yaml
    from qq_onebot_whitelist.config import load_config

    p = tmp_path / 'config.yaml'
    p.write_text(yaml.safe_dump({'ai_context': {
        'enabled': True,
        'allowed_windows': ['18:00-09:00'],
        'all_day_weekdays': ['sat', 'sun'],
    }}, allow_unicode=True), encoding='utf-8')

    cfg = load_config(p)
    assert cfg.ai_context_all_day_weekdays == ['sat', 'sun']

"""负载感知调度：高负载时推迟图片处理/维护重活。"""

from __future__ import annotations

import json

from qq_onebot_whitelist.collection import (
    defer_event_image,
    deferred_image_count,
    pop_deferred_image,
    requeue_deferred_image,
)
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.load_aware import load_aware_ok, system_cpu_percent


def test_system_cpu_percent_returns_float():
    value = system_cpu_percent()
    assert isinstance(value, float)
    assert 0.0 <= value <= 100.0


def test_load_aware_ok_when_disabled():
    config = AppConfig(load_aware_enabled=False, load_aware_cpu_threshold=80)
    assert load_aware_ok(config, cpu=99.0) is True


def test_load_aware_ok_respects_threshold():
    config = AppConfig(load_aware_enabled=True, load_aware_cpu_threshold=80)
    assert load_aware_ok(config, cpu=50.0) is True
    assert load_aware_ok(config, cpu=85.0) is False


def test_deferred_image_queue_fifo_and_requeue():
    while pop_deferred_image() is not None:
        pass
    assert defer_event_image(('a', 1)) is True
    assert defer_event_image(('b', 2)) is True
    assert deferred_image_count() == 2
    assert pop_deferred_image() == ('a', 1)
    requeue_deferred_image(('a', 1))
    assert pop_deferred_image() == ('a', 1)
    assert pop_deferred_image() == ('b', 2)
    assert deferred_image_count() == 0


def test_collect_event_defers_image_when_cpu_busy(tmp_path, monkeypatch):
    from qq_onebot_whitelist import collection
    from qq_onebot_whitelist.store import Store

    while pop_deferred_image() is not None:
        pass
    db = tmp_path / 'data' / 'bot.db'
    db.parent.mkdir(parents=True)
    store = Store(db)
    config = AppConfig(
        data_dir=tmp_path / 'data',
        load_aware_enabled=True,
        load_aware_cpu_threshold=80,
        feature_image_processing=True,
    )
    monkeypatch.setattr(collection, 'load_aware_ok', lambda cfg: False)
    event = {
        'post_type': 'message',
        'message_type': 'group',
        'group_id': '1',
        'user_id': 'u1',
        'message': [{'type': 'image', 'data': {'url': 'http://127.0.0.1:1/x.png'}}],
    }
    collection.collect_event(store, event, config)
    assert deferred_image_count() == 1
    item = pop_deferred_image()
    assert item is not None and item[2]['url'] == 'http://127.0.0.1:1/x.png'
    assert deferred_image_count() == 0

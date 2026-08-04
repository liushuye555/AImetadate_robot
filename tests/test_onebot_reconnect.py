"""bot 主连接失败重试 + 退出时状态如实 bot:false。"""

import asyncio

import pytest

from qq_onebot_whitelist import onebot
from qq_onebot_whitelist.config import AppConfig


def test_run_retries_ws_connect_and_marks_bot_down_on_exit(tmp_path, monkeypatch):
    calls = {'connect': 0, 'sleep': 0, 'status': []}

    class ConnRefused(ConnectionRefusedError):
        pass

    class StopRetry(Exception):
        pass

    class FakeWs:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    def fake_connect(url):
        calls['connect'] += 1
        if calls['connect'] == 1:
            raise ConnRefused()
        return FakeWs()

    async def fake_call(ws, action, params):
        return {'data': {'user_id': 1, 'nickname': 'test'}}

    async def fake_sleep(secs):
        calls['sleep'] += 1
        if calls['sleep'] >= 2:
            raise StopRetry()

    async def fake_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(onebot.websockets, 'connect', fake_connect)
    monkeypatch.setattr(onebot, 'call_action', fake_call)
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(onebot, 'background_sync_loop', fake_noop)
    monkeypatch.setattr(onebot, 'image_worker_loop', fake_noop)
    monkeypatch.setattr(onebot, 'startup_history_catchup_worker', fake_noop)
    monkeypatch.setattr(onebot, 'daily_report_loop', fake_noop)
    monkeypatch.setattr(onebot, 'ai_context_loop', fake_noop)
    monkeypatch.setattr(onebot, 'keepalive_loop', fake_noop)
    monkeypatch.setattr(onebot, 'status_writer_loop', fake_noop)

    from qq_onebot_whitelist import control
    monkeypatch.setattr(control, 'write_status', lambda payload: calls['status'].append(payload))
    monkeypatch.setattr(control, 'port_open', lambda *a: False)
    monkeypatch.setattr(onebot, 'Store', lambda *a, **k: object())

    config = AppConfig(data_dir=tmp_path / 'data')
    with pytest.raises(StopRetry):
        asyncio.run(onebot.run(config))
    assert calls['connect'] == 2  # 首次失败后重试成功
    assert calls['status'][-1]['bot'] is False  # 退出状态如实
    assert calls['status'][-1]['onebot'] is False

import asyncio
import json

import websockets

from qq_onebot_whitelist.onebot import run


class FakeStore:
    def __init__(self):
        self.events = []
    def clear_missing_image_paths(self, *a, **k): return 0


def test_run_starts_event_loop_before_startup_history(monkeypatch, tmp_path):
    # Regression: startup_history_catchup used to run on the event websocket before async-for,
    # so user commands arriving during catch-up could be consumed/discarded by call_action.
    # This static guard keeps run() structured with startup catch-up in a background task.
    import inspect
    src = inspect.getsource(run)
    assert 'startup_task = asyncio.create_task(startup_history_catchup_worker(config, store))' in src
    assert 'async for raw in ws:' in src
    assert src.index('startup_task = asyncio.create_task') < src.index('async for raw in ws:')

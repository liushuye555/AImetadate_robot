import asyncio
import json

from qq_onebot_whitelist import control
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import status_writer_loop


def test_status_writer_loop_writes_login_info(tmp_path, monkeypatch):
    class FakeWS:
        def __init__(self):
            self.sent = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send(self, message):
            self.sent = json.loads(message)

        async def recv(self):
            return json.dumps(
                {"echo": self.sent["echo"], "data": {"user_id": "123", "nickname": "柳树叶"}},
                ensure_ascii=False,
            )

    async def fake_sleep(_seconds):
        raise KeyboardInterrupt  # 跳出循环

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: port == control.NAPCAT_PORT)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.websockets.connect", lambda *args, **kwargs: FakeWS())
    monkeypatch.setattr("qq_onebot_whitelist.onebot.asyncio.sleep", fake_sleep)

    async def main():
        try:
            await status_writer_loop(None, AppConfig(onebot_ws_url="ws://127.0.0.1:3001"))
        except KeyboardInterrupt:
            pass

    asyncio.run(main())
    data = control.load_status()
    assert data["napcat"] is True
    assert data["onebot"] is True
    assert data["bot"] is True
    assert data["qqLoggedIn"] is True
    assert data["qqNumber"] == "123"
    assert data["qqNickname"] == "柳树叶"

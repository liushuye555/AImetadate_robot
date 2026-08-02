import asyncio

from qq_onebot_whitelist import control
from qq_onebot_whitelist.onebot import status_writer_loop


def test_status_writer_loop_writes_login_info(tmp_path, monkeypatch):
    async def fake_sleep(_seconds):
        raise KeyboardInterrupt  # 跳出循环

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: port == control.NAPCAT_PORT)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.is_collection_paused", lambda: False)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.asyncio.sleep", fake_sleep)

    async def main():
        try:
            await status_writer_loop(
                None,
                None,
                {"qqLoggedIn": True, "qqNumber": "123", "qqNickname": "柳树叶"},
            )
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

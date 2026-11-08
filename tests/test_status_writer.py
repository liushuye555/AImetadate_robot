import asyncio
import pytest

from qq_onebot_whitelist import control
from qq_onebot_whitelist.onebot import status_writer_loop
from qq_onebot_whitelist.config import AppConfig


@pytest.mark.parametrize('provider,known,online', [('napcat', True, True), ('external', False, False)])
def test_status_writer_loop_writes_login_info(tmp_path, monkeypatch, provider, known, online):
    async def fake_sleep(_seconds):
        raise KeyboardInterrupt  # 跳出循环

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: port == control.NAPCAT_PORT)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.is_collection_paused", lambda: False)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.asyncio.sleep", fake_sleep)
    async def probe(_config):
        return {"qqLoggedIn": online, "qqStatusKnown": known,
                "qqNumber": "123", "qqNickname": "柳树叶"}
    monkeypatch.setattr("qq_onebot_whitelist.onebot.probe_login_info", probe)

    async def main():
        try:
            await status_writer_loop(
                None,
                AppConfig(onebot_provider=provider),
                {"qqLoggedIn": True, "qqNumber": "123", "qqNickname": "柳树叶"},
            )
        except KeyboardInterrupt:
            pass

    asyncio.run(main())
    data = control.load_status()
    assert data["napcat"] is (provider == 'napcat')
    assert data['gatewayProvider'] == provider
    assert data['gatewayRunning'] is True
    assert data['qqStatusKnown'] is known
    assert data["onebot"] is True
    assert data["bot"] is True
    assert data["qqLoggedIn"] is online
    assert data["qqNumber"] == "123"
    assert data["qqNickname"] == "柳树叶"

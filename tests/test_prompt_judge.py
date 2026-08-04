"""提示词绑定 LLM 复核测试。"""

from __future__ import annotations

from qq_onebot_whitelist import prompt_judge
from qq_onebot_whitelist.prompt_judge import prompt_hash, should_keep_prompt
from qq_onebot_whitelist.store import Store


def test_should_keep_prompt_rule_mode_always_keeps():
    assert should_keep_prompt("1girl, solo", mode="rule") is True


def test_llm_judge_parses_verdict(tmp_path, monkeypatch):
    def fake_llm(text):
        return True, 90
    monkeypatch.setattr(prompt_judge, 'llm_judge_prompt', fake_llm)
    assert should_keep_prompt("1girl, solo", mode="llm") is True


def test_llm_judge_rejects_chat(tmp_path, monkeypatch):
    def fake_llm(text):
        return False, 60
    monkeypatch.setattr(prompt_judge, 'llm_judge_prompt', fake_llm)
    assert should_keep_prompt("1girl 好可爱", mode="llm") is False


def test_prompt_judge_cache_store(tmp_path):
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    assert store.get_prompt_judge('abc') is None
    store.set_prompt_judge('abc', True, 100)
    assert store.get_prompt_judge('abc') is True
    store.set_prompt_judge('abc', False)
    assert store.get_prompt_judge('abc') is False


def test_reclassify_prompt_judge_downgrades_rejected(tmp_path, monkeypatch):
    import sqlite3
    from qq_onebot_whitelist.maintenance import reclassify_prompt_judge
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    img = tmp_path / 'a.png'
    img.write_bytes(b'x')
    store.record_image(scope='group:1', user_id='u', result={
        'sha256': 'a', 'format': 'PNG', 'size': 1, 'width': 64, 'height': 64,
        'kept_path': str(img), 'retention_reason': 'prompt_bound',
        'bound_prompt': '1girl 好可爱',
    }, raw={'message_db_id': None})
    monkeypatch.setattr(prompt_judge, 'llm_judge_prompt', lambda text: (False, 10))
    changed = reclassify_prompt_judge(tmp_path, mode='llm')
    assert changed == 1
    conn = sqlite3.connect(db)
    reason = conn.execute("SELECT retention_reason FROM images").fetchone()[0]
    conn.close()
    assert reason == 'candidate'
    assert prompt_hash('1girl 好可爱') is not None

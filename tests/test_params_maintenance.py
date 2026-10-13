import sqlite3

from qq_onebot_whitelist import ai_discussion_judge
from qq_onebot_whitelist.maintenance import reclassify_params_judge
from qq_onebot_whitelist.store import Store


def _add_params_image(store: Store, prompt: str) -> int:
    store.record_image(
        scope='group:1',
        user_id='user',
        result={'retention_reason': 'params_discussion', 'bound_prompt': prompt},
        raw={},
    )
    with store._conn() as conn:
        return int(conn.execute('SELECT MAX(id) FROM images').fetchone()[0])


def test_params_judge_skips_discussion_records_and_reclassifies_legacy(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data' / 'bot.db')
    reviewed = {
        'selected': _add_params_image(store, 'selected derived prompt'),
        'pending': _add_params_image(store, 'pending derived prompt'),
        'manual_reject': _add_params_image(store, 'manual rejection prompt'),
    }
    store.set_image_discussion(reviewed['selected'], 'selected', 'reviewed', manual=False)
    store.set_image_discussion(reviewed['pending'], 'pending', 'awaiting review', manual=False)
    store.set_image_discussion(reviewed['manual_reject'], 'rejected', 'human rejected', manual=True)
    legacy = _add_params_image(store, 'legacy prompt')

    seen_batches = []

    def fake_judge(texts, *, store):
        seen_batches.append(texts)
        return [False for _ in texts]

    monkeypatch.setattr(ai_discussion_judge, 'judge_params_batch', fake_judge)

    assert reclassify_params_judge(tmp_path, mode='llm') == 1
    assert seen_batches == [['legacy prompt']]
    with sqlite3.connect(store.path) as conn:
        rows = dict(conn.execute('SELECT id, retention_reason FROM images').fetchall())
        prompts = dict(conn.execute('SELECT id, bound_prompt FROM images').fetchall())
    assert rows[reviewed['selected']] == 'params_discussion'
    assert rows[reviewed['pending']] == 'params_discussion'
    assert rows[reviewed['manual_reject']] == 'params_discussion'
    assert rows[legacy] == 'candidate'
    assert prompts[legacy] is None


def test_params_judge_update_rechecks_discussion_record(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data' / 'bot.db')
    legacy = _add_params_image(store, 'legacy prompt')

    def judge_then_add_discussion(texts, *, store):
        assert texts == ['legacy prompt']
        store.set_image_discussion(legacy, 'selected', 'reviewed while judging')
        return [False]

    monkeypatch.setattr(ai_discussion_judge, 'judge_params_batch', judge_then_add_discussion)

    assert reclassify_params_judge(tmp_path, mode='llm') == 0
    with sqlite3.connect(store.path) as conn:
        row = conn.execute('SELECT retention_reason, bound_prompt FROM images WHERE id=?', (legacy,)).fetchone()
    assert row == ('params_discussion', 'legacy prompt')

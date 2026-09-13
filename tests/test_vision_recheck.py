"""视觉复核：错分图降级、结果缓存、限量、开关与按类目判定标准。"""
from pathlib import Path

from qq_onebot_whitelist.store import Store
from qq_onebot_whitelist import vision_recheck


def make_store(tmp_path: Path) -> Store:
    (tmp_path / 'data').mkdir(exist_ok=True)
    store = Store(tmp_path / 'data' / 'bot.db')
    for index, (sha, reason) in enumerate([
        ('sha1', 'params_discussion'),
        ('sha2', 'prompt_bound'),
        ('sha3', 'params_discussion'),
        ('sha4', 'positive_feedback'),
    ]):
        img = tmp_path / f'img{index}.png'
        img.write_bytes(b'x' * 64)
        store.record_image(scope='group:1', user_id='u', result={
            'sha256': sha, 'format': 'PNG', 'size': 64, 'width': 64, 'height': 64,
            'kept_path': str(img), 'retention_reason': reason, 'text_excerpt': f'上下文{index}',
        }, raw={})
    return store


class FakeConfig:
    vision_recheck_enabled = True
    vision_recheck_batch = 20
    ai_context_allowed_windows: list[str] = []
    ai_context_all_day_weekdays: list[str] = []


def test_recheck_demotes_non_ai_images(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    # 依次判定（id DESC）：sha4(AI) → sha3(非AI) → sha2(AI) → sha1(非AI)
    verdicts = [{'is_ai_image': True, 'tokens': 10},
                {'is_ai_image': False, 'tokens': 10},
                {'is_ai_image': True, 'tokens': 10},
                {'is_ai_image': False, 'tokens': 10}]
    seen_modes = []

    def fake_judge(cfg, path, ctx, mode='strict'):
        seen_modes.append(mode)
        return verdicts.pop(0)

    monkeypatch.setattr(vision_recheck, 'judge_image', fake_judge)

    result = vision_recheck.recheck_batch(tmp_path, FakeConfig(), force=True)

    assert result == {'checked': 4, 'demoted': 2}
    import sqlite3
    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    rows = dict(conn.execute('SELECT sha256, retention_reason FROM images').fetchall())
    conn.close()
    assert rows['sha1'] == 'candidate'           # 非 AI 降级
    assert rows['sha2'] == 'prompt_bound'        # AI 图保留
    assert rows['sha3'] == 'candidate'           # 非 AI 降级
    assert rows['sha4'] == 'positive_feedback'   # AI 图保留
    # 类目决定判定标准：参数讨论=related，提示词绑定/群友好评=strict
    assert set(seen_modes) == {'related', 'strict'}


def test_recheck_verdict_cached_never_repeats(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr(vision_recheck, 'judge_image',
                        lambda cfg, path, ctx, mode='strict': {'is_ai_image': True, 'tokens': 5})

    assert vision_recheck.recheck_batch(tmp_path, FakeConfig(), force=True)['checked'] == 4
    # 第二轮全部命中缓存：不再调用 judge
    monkeypatch.setattr(vision_recheck, 'judge_image',
                        lambda cfg, path, ctx, mode='strict': (_ for _ in ()).throw(AssertionError('should not judge')))
    assert vision_recheck.recheck_batch(tmp_path, FakeConfig(), force=True)['checked'] == 0


def test_recheck_respects_batch_limit(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr(vision_recheck, 'judge_image',
                        lambda cfg, path, ctx, mode='strict': {'is_ai_image': True, 'tokens': 5})
    result = vision_recheck.recheck_batch(tmp_path, FakeConfig(), limit=2, force=True)
    assert result['checked'] == 2
    # 剩 2 张未复核
    assert len(store.vision_unchecked_images(
        categories=tuple(vision_recheck.CATEGORY_MODES), limit=10)) == 2


def test_recheck_disabled_without_force(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr(vision_recheck, 'judge_image',
                        lambda cfg, path, ctx, mode='strict': {'is_ai_image': True, 'tokens': 5})
    result = vision_recheck.recheck_batch(tmp_path, FakeConfig(), force=True)
    assert result['checked'] == 4

    result = vision_recheck.recheck_batch(tmp_path, store=None, force=False) if False else \
        vision_recheck.recheck_batch(tmp_path, type('C', (), {'vision_recheck_enabled': False})(), force=False)
    assert result['checked'] == 0


def test_category_modes_cover_recheck_categories(tmp_path):
    store = make_store(tmp_path)
    rows = store.vision_unchecked_images(
        categories=tuple(vision_recheck.CATEGORY_MODES), limit=10)
    assert len(rows) == 4
    # 返回带类目，供 recheck_batch 选择判定标准
    assert all(len(row) == 5 and row[4] in vision_recheck.CATEGORY_MODES for row in rows)

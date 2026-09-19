"""孤儿临时文件清理：只删超龄的 .download-* 等，正在处理的不动。"""
import os
import time

from qq_onebot_whitelist.maintenance import cleanup_stale_tmp_files


def test_cleanup_removes_only_stale_files(tmp_path):
    tmp = tmp_path / 'data' / 'tmp'
    tmp.mkdir(parents=True)
    stale = tmp / '.download-abc123.png'
    stale.write_bytes(b'x' * 8)
    fresh = tmp / '.download-def456.jpg'
    fresh.write_bytes(b'y' * 8)
    old = time.time() - 25 * 3600
    os.utime(stale, (old, old))  # 25 小时前 → 该删
    # 24 小时内 → 保留

    removed = cleanup_stale_tmp_files(tmp_path, max_age_hours=24)

    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_ignores_directories_and_missing_dir(tmp_path):
    (tmp_path / 'data' / 'tmp' / 'subdir').mkdir(parents=True)
    assert cleanup_stale_tmp_files(tmp_path) == 0
    assert (tmp_path / 'data' / 'tmp' / 'subdir').exists()
    # 目录不存在时不报错
    assert cleanup_stale_tmp_files(tmp_path / 'empty') == 0


def test_sync_reports_stale_tmp_removed(tmp_path, monkeypatch):
    from qq_onebot_whitelist import maintenance
    from qq_onebot_whitelist.store import Store
    (tmp_path / 'data' / 'tmp').mkdir(parents=True)
    (tmp_path / 'data' / 'images').mkdir(parents=True)
    stale = tmp_path / 'data' / 'tmp' / '.download-old.png'
    stale.write_bytes(b'x')
    old = time.time() - 30 * 3600
    os.utime(stale, (old, old))
    store = Store(tmp_path / 'data' / 'bot.db')
    monkeypatch.setattr(maintenance, 'Store', lambda _p: store)
    monkeypatch.setattr(maintenance, 'deduplicate_image_storage', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'cleanup_expired_candidates', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'reclassify_possible_obfuscation', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'restore_confirmed_obfuscation', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'reclassify_historical_03', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'backfill_prompt_keys', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'reclassify_prompt_judge', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'reclassify_params_judge', lambda *_a, **_k: 0)
    monkeypatch.setattr(maintenance, 'prune_empty_dirs', lambda *_a, **_k: 0)
    import qq_onebot_whitelist.build_image_view as biv
    monkeypatch.setattr(biv, 'build_view', lambda *_a, **_k: {})
    import qq_onebot_whitelist.resource_view as rv
    monkeypatch.setattr(rv, 'write_resource_pages', lambda *_a, **_k: {})

    result = maintenance.sync_image_files(tmp_path, ttl_hours=24)

    assert result['stale_tmp_removed'] == 1
    assert not stale.exists()

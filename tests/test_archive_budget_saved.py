from qq_onebot_whitelist.archive_budget import enforce_archive_budget


def test_archive_budget_does_not_delete_saved_ai_archive(tmp_path):
    root = tmp_path / 'ai'
    root.mkdir()
    saved = root / 'saved.png'
    saved.write_bytes(b'x' * 20)
    removed = enforce_archive_budget(root, [
        {'id': 1, 'kept_path': str(saved), 'retention_reason': 'nearby_ai_context'},
    ], max_bytes=1, enabled=False)
    assert removed == []
    assert saved.exists()

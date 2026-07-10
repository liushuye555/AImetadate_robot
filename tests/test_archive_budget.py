from qq_onebot_whitelist.archive_budget import archive_size_bytes, enforce_archive_budget


def write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)


def test_enforce_archive_budget_removes_low_value_old_files_first(tmp_path):
    archive = tmp_path / 'ai'
    low = archive / 'aa' / 'low.png'
    high = archive / 'bb' / 'high.png'
    write(low, 80)
    write(high, 80)
    records = [
        {'kept_path': str(low), 'retention_reason': 'nearby_ai_context', 'has_ai_metadata': False, 'id': 1},
        {'kept_path': str(high), 'retention_reason': 'ai_metadata', 'has_ai_metadata': True, 'id': 2},
    ]

    removed = enforce_archive_budget(archive, records, max_bytes=100)

    assert low in removed
    assert not low.exists()
    assert high.exists()
    assert archive_size_bytes(archive) <= 100

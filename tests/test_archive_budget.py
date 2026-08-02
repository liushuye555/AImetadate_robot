from qq_onebot_whitelist.archive_budget import archive_size_bytes, enforce_archive_budget


def write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)


def test_enforce_archive_budget_removes_low_value_old_files_first(tmp_path):
    archive = tmp_path / 'ai'
    cand = archive / 'aa' / 'cand.png'
    kept = archive / 'bb' / 'kept.png'
    write(cand, 80)
    write(kept, 80)
    records = [
        {'kept_path': str(cand), 'retention_reason': 'candidate', 'has_ai_metadata': False, 'id': 1},
        {'kept_path': str(kept), 'retention_reason': 'ai_metadata', 'has_ai_metadata': True, 'id': 2},
    ]

    removed = enforce_archive_budget(archive, records, max_bytes=100)

    assert cand in removed
    assert not cand.exists()
    assert kept.exists()


def test_enforce_archive_budget_only_deletes_candidates(tmp_path):
    archive = tmp_path / 'ai'
    ai = archive / 'aa' / 'ai.png'
    context = archive / 'bb' / 'ctx.png'
    feedback = archive / 'cc' / 'fb.png'
    cand = archive / 'dd' / 'cand.png'
    write(ai, 1000)
    write(context, 1000)
    write(feedback, 1000)
    write(cand, 1000)
    records = [
        {'kept_path': str(ai), 'retention_reason': 'ai_metadata', 'has_ai_metadata': True, 'id': 1},
        {'kept_path': str(context), 'retention_reason': 'nearby_ai_context', 'has_ai_metadata': False, 'id': 2},
        {'kept_path': str(feedback), 'retention_reason': 'positive_feedback', 'has_ai_metadata': False, 'id': 3},
        {'kept_path': str(cand), 'retention_reason': 'candidate', 'has_ai_metadata': False, 'id': 4},
    ]

    removed = enforce_archive_budget(archive, records, max_bytes=100)

    assert cand in removed
    assert not cand.exists()
    assert ai.exists()
    assert context.exists()
    assert feedback.exists()

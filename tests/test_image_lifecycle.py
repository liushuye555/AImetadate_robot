from pathlib import Path

from qq_onebot_whitelist.image_lifecycle import CandidateImage, find_recent_candidate, promote_candidate, cleanup_candidates


def test_find_recent_candidate_selects_latest_same_scope(tmp_path):
    old = CandidateImage(scope='group:1', sha256='old', path=tmp_path/'old.png', created_at=1000, score=0)
    new = CandidateImage(scope='group:1', sha256='new', path=tmp_path/'new.png', created_at=1100, score=0)
    other = CandidateImage(scope='group:2', sha256='other', path=tmp_path/'other.png', created_at=1200, score=0)

    found = find_recent_candidate([old, new, other], scope='group:1', now=1200, window_seconds=300)

    assert found == new


def test_promote_candidate_moves_file_to_archive(tmp_path):
    src = tmp_path / 'candidate.png'
    src.write_bytes(b'image')
    candidate = CandidateImage(scope='group:1', sha256='abcdef', path=src, created_at=1000, score=2)

    dest = promote_candidate(candidate, tmp_path / 'archive')

    assert dest.exists()
    assert dest.read_bytes() == b'image'
    assert not src.exists()
    assert dest.name == 'abcdef.png'


def test_cleanup_candidates_removes_expired_files(tmp_path):
    old_path = tmp_path / 'old.png'
    fresh_path = tmp_path / 'fresh.png'
    old_path.write_bytes(b'old')
    fresh_path.write_bytes(b'fresh')
    candidates = [
        CandidateImage(scope='group:1', sha256='old', path=old_path, created_at=0, score=0),
        CandidateImage(scope='group:1', sha256='fresh', path=fresh_path, created_at=3600, score=0),
    ]

    kept = cleanup_candidates(candidates, now=7200, ttl_seconds=4000)

    assert [c.sha256 for c in kept] == ['fresh']
    assert not old_path.exists()
    assert fresh_path.exists()

"""Restoration races and migration checks using only synthetic fixtures."""

import hashlib
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from qq_onebot_whitelist import gilbert_obfuscation as gilbert
from qq_onebot_whitelist import maintenance
from qq_onebot_whitelist.store import Store


def _make_obfuscated(path, *, layers=1):
    width, height = 72, 54
    source = path.with_name('synthetic-source.png')
    image = Image.new('RGB', (width, height))
    image.putdata([
        (30 + 2 * x, 35 + 3 * y, 25 + x + y)
        for y in range(height) for x in range(width)
    ])
    image.save(source)
    gilbert.restore_image(source, path, layers=layers, direction='decode')
    return source


def _record_image(store, path, digest, reason, *, deobfuscated=False):
    store.record_image(
        scope='synthetic-review', user_id='synthetic',
        result={
            'sha256': digest, 'format': 'PNG', 'size': path.stat().st_size,
            'width': 72, 'height': 54, 'kept_path': str(path),
            'retention_reason': reason, 'deobfuscated': deobfuscated,
        }, raw={},
    )


def test_concurrent_promotion_cannot_replace_original_backup(tmp_path, monkeypatch):
    """The second copier sees the promoted source after both existence checks."""
    archive = tmp_path / 'images' / 'ai'
    digest = 'a' * 64
    original = archive / digest[:2] / f'{digest}.png'
    original.parent.mkdir(parents=True)
    original_bytes = b'synthetic-obfuscated-original'
    restored_bytes = b'synthetic-restored-content'
    original.write_bytes(original_bytes)
    first_output = tmp_path / 'first.png'
    second_output = tmp_path / 'second.png'
    first_output.write_bytes(restored_bytes)
    second_output.write_bytes(restored_bytes)

    second_started = threading.Event()
    first_finished = threading.Event()
    real_copy = shutil.copy2

    def delayed_copy(src, dest, *args, **kwargs):
        if (threading.current_thread().name == 'second-promotion'
                and Path(src) == original
                and Path(dest).name.startswith('.original-')):
            second_started.set()
            assert first_finished.wait(10), 'First promotion did not finish'
        return real_copy(src, dest, *args, **kwargs)

    def promote_first():
        threading.current_thread().name = 'first-promotion'
        assert second_started.wait(10), 'Second backup copy did not start'
        result = gilbert.promote_restored(original, first_output, archive, digest)
        first_finished.set()
        return result

    def promote_second():
        threading.current_thread().name = 'second-promotion'
        return gilbert.promote_restored(original, second_output, archive, digest)

    monkeypatch.setattr(shutil, 'copy2', delayed_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(promote_first)
        second = pool.submit(promote_second)
        assert first.result(timeout=15) == second.result(timeout=15) == original

    backup = archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png'
    assert backup.read_bytes() == original_bytes
    assert original.read_bytes() == restored_bytes
    assert not list(backup.parent.glob('.original-*'))
    assert not list(original.parent.glob('.restored-*'))


def test_concurrent_safe_restore_uses_separate_snapshots_and_outputs(tmp_path, monkeypatch):
    original = tmp_path / 'scrambled.png'
    source = _make_obfuscated(original, layers=3)
    original_bytes = original.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    archive = tmp_path / 'images' / 'ai'
    shared_output = tmp_path / 'tmp' / f'{digest}.restore.png'
    barrier = threading.Barrier(2)
    real_restore = gilbert.restore_image
    observed_paths = []
    lock = threading.Lock()

    def synchronized_restore(src, dest, *args, **kwargs):
        with lock:
            observed_paths.append((Path(src), Path(dest)))
        barrier.wait(timeout=10)
        return real_restore(src, dest, *args, **kwargs)

    monkeypatch.setattr(gilbert, 'restore_image', synchronized_restore)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(
            gilbert.safe_restore, original, shared_output, archive, digest,
            layers=3, direction='encode',
        ) for _ in range(2)]
        promoted = [future.result(timeout=15) for future in results]

    expected = archive / digest[:2] / f'{digest}.png'
    assert promoted == [expected, expected]
    assert len({src for src, _ in observed_paths}) == 2
    assert len({dest for _, dest in observed_paths}) == 2
    with Image.open(source) as before, Image.open(expected) as after:
        assert before.tobytes() == after.tobytes()
    backup = archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png'
    assert backup.read_bytes() == original_bytes
    assert not list(shared_output.parent.glob('obfuscation-restore-*'))


def test_cached_operation_replayed_on_restored_file_preserves_pixels_and_backup(tmp_path):
    original = tmp_path / 'scrambled.png'
    _make_obfuscated(original, layers=3)
    original_bytes = original.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    archive = tmp_path / 'images' / 'ai'
    output = tmp_path / 'tmp' / 'shared.png'
    promoted = gilbert.safe_restore(original, output, archive, digest, layers=3, direction='encode')
    assert promoted is not None
    restored_bytes = promoted.read_bytes()

    assert gilbert.safe_restore(promoted, output, archive, digest, layers=3, direction='encode') is None
    assert promoted.read_bytes() == restored_bytes
    backup = archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png'
    assert backup.read_bytes() == original_bytes


def test_same_sha_context_sibling_is_propagated_without_reapplying_restore(tmp_path):
    archive = tmp_path / 'data' / 'images' / 'ai'
    original = tmp_path / 'scrambled.png'
    _make_obfuscated(original)
    original_bytes = original.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    canonical = archive / digest[:2] / f'{digest}.png'
    canonical.parent.mkdir(parents=True)
    original.replace(canonical)
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    _record_image(store, canonical, digest, 'prompt_bound')
    _record_image(store, canonical, digest, 'positive_feedback')
    detected = gilbert.analyze_image(canonical)
    maintenance._save_detection(store, digest, detected)

    assert maintenance.restore_confirmed_obfuscation(tmp_path) == 1
    restored_bytes = canonical.read_bytes()
    assert maintenance.propagate_deobfuscated(tmp_path) == 1
    assert maintenance.restore_confirmed_obfuscation(tmp_path) == 0
    assert canonical.read_bytes() == restored_bytes
    backup = archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png'
    assert backup.read_bytes() == original_bytes
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT deobfuscated FROM images ORDER BY id').fetchall() == [(1,), (1,)]


@pytest.mark.parametrize('reason', ['prompt_bound', 'params_discussion', 'positive_feedback'])
@pytest.mark.parametrize('legacy_confidence', ['none', 'possible'])
def test_context_legacy_cache_is_rechecked_and_restored(tmp_path, reason, legacy_confidence):
    original = tmp_path / 'scrambled.png'
    _make_obfuscated(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    _record_image(store, original, digest, reason)
    store.save_obfuscation_score(
        digest, ratio=0.5, layers=1, obfuscated=legacy_confidence == 'possible',
        confidence=legacy_confidence, version=0,
    )

    assert maintenance.restore_confirmed_obfuscation(tmp_path, max_rechecks=1) == 1
    assert store.obfuscation_details(digest)['detector_version'] == gilbert.DETECTOR_VERSION
    assert store.obfuscation_details(digest)['direction'] == 'encode'
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT deobfuscated FROM images').fetchone()[0] == 1
    assert maintenance.restore_confirmed_obfuscation(tmp_path, max_rechecks=1) == 0


@pytest.mark.parametrize('outcome', ['exception', 'unsupported', 'negative'])
def test_compressed_recheck_cannot_enter_candidate_ttl_on_failure_or_negative(tmp_path, monkeypatch, outcome):
    original = tmp_path / 'scrambled.png'
    _make_obfuscated(original)
    db = tmp_path / 'data' / 'bot.db'
    store = Store(db)
    _record_image(store, original, 'b' * 64, 'xiaofanqie_compressed')

    def analyze(_path):
        if outcome == 'exception':
            raise OSError('Synthetic transient read failure')
        if outcome == 'unsupported':
            return None
        return {
            'obfuscated': False, 'ratio': 1.0, 'layers': None,
            'confidence': 'none', 'detector_version': gilbert.DETECTOR_VERSION,
        }

    monkeypatch.setattr(gilbert, 'analyze_image', analyze)
    monkeypatch.setattr(maintenance, 'analyze_image', analyze)
    assert maintenance.reclassify_possible_obfuscation(tmp_path) == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT retention_reason FROM images').fetchone()[0] == 'xiaofanqie_compressed'
    assert original.is_file()

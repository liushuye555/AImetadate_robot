from pathlib import Path
import shutil

from PIL import Image

from qq_onebot_whitelist.store import Store


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (12, 20), color=(255, 120, 90)).save(path, format='PNG')


def _write_truncated_png(path: Path) -> None:
    full = path.with_suffix('.full.png')
    _write_png(full)
    path.write_bytes(full.read_bytes()[:-12])  # remove the PNG IEND chunk


def test_verify_image_file_rejects_truncated_png(tmp_path):
    from qq_onebot_whitelist.images import verify_image_file

    complete = tmp_path / 'complete.png'
    truncated = tmp_path / 'truncated.png'
    _write_png(complete)
    _write_truncated_png(truncated)

    assert verify_image_file(complete) is None
    assert 'truncated' in (verify_image_file(truncated) or '').lower()


def test_repair_image_promotes_only_a_complete_download(tmp_path, monkeypatch):
    from qq_onebot_whitelist import image_repair
    from qq_onebot_whitelist.images import verify_image_file

    archive = tmp_path / 'data' / 'images' / 'ai'
    broken = archive / 'aa' / 'broken.png'
    _write_truncated_png(broken)
    replacement = tmp_path / 'replacement.png'
    _write_png(replacement)
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_image(
        scope='group:1', user_id='u',
        result={
            'url': 'https://images.example.test/picture.png', 'sha256': 'a' * 64,
            'size': broken.stat().st_size, 'format': 'PNG', 'width': 12, 'height': 20,
            'kept_path': str(broken), 'retention_reason': 'ai_metadata',
        }, raw={'image': {'url': 'https://images.example.test/picture.png'}},
    )

    def fake_download(url, tmp_dir, filename_hint=None, timeout=30):
        out = Path(tmp_dir) / 'download.png'
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(replacement, out)
        return out

    monkeypatch.setattr(image_repair, 'download_image', fake_download)
    result = image_repair.repair_image(
        store, 1, tmp_dir=tmp_path / 'data' / 'tmp', archive_root=archive,
    )

    row = store.get_image_record(1)
    assert result['status'] == 'repaired'
    assert row is not None
    assert row['kept_path'] != str(broken)
    assert verify_image_file(row['kept_path']) is None
    assert not broken.exists()


def test_repair_image_keeps_replacement_when_relative_archive_path_resolves_to_old_file(tmp_path, monkeypatch):
    from qq_onebot_whitelist import image_repair
    from qq_onebot_whitelist.images import sha256_file, verify_image_file

    monkeypatch.chdir(tmp_path)
    replacement = tmp_path / 'replacement.jpg'
    Image.new('RGB', (12, 20), color=(20, 80, 140)).save(replacement, format='JPEG')
    digest = sha256_file(replacement)
    broken = tmp_path / 'data' / 'images' / 'ai' / digest[:2] / f'{digest}.jpg'
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b'')
    store = Store(tmp_path / 'data' / 'bot.db')
    store.record_image(
        scope='group:1', user_id='u',
        result={
            'url': 'https://images.example.test/picture.jpg', 'sha256': digest,
            'size': 0, 'format': 'JPEG', 'width': 12, 'height': 20,
            'kept_path': str(broken), 'retention_reason': 'ai_metadata',
        }, raw={'image': {'url': 'https://images.example.test/picture.jpg'}},
    )

    def fake_download(url, tmp_dir, filename_hint=None, timeout=30):
        out = Path(tmp_dir) / 'download.jpg'
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(replacement, out)
        return out

    monkeypatch.setattr(image_repair, 'download_image', fake_download)
    result = image_repair.repair_image(
        store, 1, tmp_dir=Path('data') / 'tmp', archive_root=Path('data') / 'images' / 'ai',
    )

    row = store.get_image_record(1)
    assert result['status'] == 'repaired'
    assert row is not None
    assert Path(row['kept_path']).exists()
    assert verify_image_file(row['kept_path']) is None


def test_repair_image_reuses_healthy_image_from_same_batch_before_download(tmp_path, monkeypatch):
    from qq_onebot_whitelist import image_repair
    from qq_onebot_whitelist.images import verify_image_file

    archive = tmp_path / 'data' / 'images' / 'ai'
    healthy = archive / 'aa' / 'healthy.png'
    broken = archive / 'bb' / 'broken.png'
    _write_png(healthy)
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b'')
    store = Store(tmp_path / 'data' / 'bot.db')
    common = {
        'scope': 'group:1', 'retention_reason': 'ai_metadata', 'prompt_key': 'same-batch',
        'format': 'PNG', 'width': 12, 'height': 20,
    }
    store.record_image(
        scope='group:1', user_id='u',
        result=common | {'url': 'https://images.example.test/healthy.png', 'sha256': 'h' * 64,
                         'size': healthy.stat().st_size, 'kept_path': str(healthy)}, raw={},
    )
    store.record_image(
        scope='group:1', user_id='u',
        result=common | {'url': 'https://images.example.test/broken.png', 'sha256': 'b' * 64,
                         'size': 0, 'kept_path': str(broken)}, raw={},
    )

    def should_not_download(*args, **kwargs):
        raise AssertionError('a healthy same-batch image should be reused first')

    monkeypatch.setattr(image_repair, 'download_image', should_not_download)
    result = image_repair.repair_image(
        store, 2, tmp_dir=tmp_path / 'data' / 'tmp', archive_root=archive,
    )

    row = store.get_image_record(2)
    assert result['status'] == 'repaired'
    assert result['source_id'] == 1
    assert row is not None
    assert row['kept_path'] == str(healthy)
    assert verify_image_file(row['kept_path']) is None

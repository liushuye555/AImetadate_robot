import struct
import zlib
from pathlib import Path

from qq_onebot_whitelist.image_meta import parse_image_metadata
from qq_onebot_whitelist.image_policy import should_keep_image
from qq_onebot_whitelist.images import existing_content_path, process_image_url


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + kind + payload + b'\x00\x00\x00\x00'


def make_png(chunks):
    ihdr = struct.pack('>IIBBBBB', 920, 1536, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr) + b''.join(chunks) + png_chunk(b'IEND', b'')


def test_parse_png_detects_comfyui_ztxt_without_decoding_pixels(tmp_path):
    payload = b'prompt\x00' + zlib.compress(b'{"class_type":"KSampler","inputs":{"ckpt_name":"model.safetensors"}}')
    path = tmp_path / 'ai.png'
    path.write_bytes(make_png([png_chunk(b'zTXt', payload)]))

    meta = parse_image_metadata(path)

    assert meta.format == 'PNG'
    assert meta.width == 920
    assert meta.height == 1536
    assert meta.has_ai_metadata is True
    assert meta.ai_source == 'ComfyUI'
    assert 'prompt' in meta.metadata_keys


def test_plain_png_is_not_kept(tmp_path):
    path = tmp_path / 'plain.png'
    path.write_bytes(make_png([]))
    meta = parse_image_metadata(path)

    keep, reason = should_keep_image(meta)

    assert keep is False
    assert reason == 'no_ai_metadata'


def test_ai_png_is_kept(tmp_path):
    payload = b'workflow\x00' + zlib.compress(b'{"nodes":[{"class_type":"KSampler"}]}')
    path = tmp_path / 'ai.png'
    path.write_bytes(make_png([png_chunk(b'zTXt', payload)]))
    meta = parse_image_metadata(path)

    keep, reason = should_keep_image(meta)

    assert keep is True
    assert reason == 'ai_metadata'


def test_existing_content_prefers_archive_over_candidate_and_extension(tmp_path):
    archive = tmp_path / 'ai' / 'ab' / 'abcdef.jpg'
    candidate = tmp_path / 'candidates' / 'ab' / 'abcdef.png'
    archive.parent.mkdir(parents=True)
    candidate.parent.mkdir(parents=True)
    archive.write_bytes(b'image')
    candidate.write_bytes(b'image')

    assert existing_content_path('abcdef', tmp_path / 'ai', tmp_path / 'candidates') == archive


def test_kept_duplicate_promotes_existing_candidate(monkeypatch, tmp_path):
    from PIL import Image

    candidate = tmp_path / 'candidates' / 'ab' / ('ab' * 32 + '.png')
    candidate.parent.mkdir(parents=True)
    Image.new('RGB', (2, 2), color=(20, 40, 60)).save(candidate, format='PNG')
    incoming = tmp_path / 'incoming.png'
    Image.new('RGB', (2, 2), color=(20, 40, 60)).save(incoming, format='PNG')
    monkeypatch.setattr('qq_onebot_whitelist.images.download_image', lambda *args, **kwargs: incoming)
    monkeypatch.setattr('qq_onebot_whitelist.images.sha256_file', lambda path: 'ab' * 32)
    monkeypatch.setattr('qq_onebot_whitelist.images.should_keep_image', lambda *args, **kwargs: (True, 'positive_feedback'))

    result = process_image_url(
        'https://example.test/image',
        tmp_dir=tmp_path / 'tmp',
        archive_root=tmp_path / 'ai',
        candidate_root=tmp_path / 'candidates',
    )

    assert result['retention_reason'] == 'positive_feedback'
    assert Path(result['kept_path']).is_relative_to(tmp_path / 'ai')
    assert not candidate.exists()


def test_download_image_uses_unique_temp_files_to_avoid_concurrent_overwrite(tmp_path, monkeypatch):
    import io
    import qq_onebot_whitelist.images as images

    class Response:
        def __enter__(self):
            return io.BytesIO(b'complete-image-bytes')

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(images.urllib.request, 'urlopen', lambda *args, **kwargs: Response())

    first = images.download_image('https://example.test/same.png', tmp_path)
    second = images.download_image('https://example.test/same.png', tmp_path)

    assert first != second
    assert first.read_bytes() == b'complete-image-bytes'
    assert second.read_bytes() == b'complete-image-bytes'
